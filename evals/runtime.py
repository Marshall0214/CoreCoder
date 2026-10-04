"""Fresh task tools, redacted events and a budgeted CoreCoder LLM adapter."""

import hashlib
import inspect
import json
import os
import threading
import time
import uuid
from pathlib import Path

from corecoder.tools.base import Tool
from corecoder.tools.bash import BashTool
from corecoder.tools.edit import EditFileTool
from corecoder.tools.glob_tool import GlobTool
from corecoder.tools.grep import GrepTool
from corecoder.tools.read import ReadFileTool
from corecoder.tools.search_code import SearchCodeTool
from corecoder.tools.todo import TodoWriteTool
from corecoder.tools.write import WriteFileTool

from .context_policy import request_breakdown
from .process import run_tests
from .schema import RunConfig

VISIBLE_COMMAND = "python -m unittest discover -s tests -v"


class BudgetExceeded(RuntimeError):
    pass


class Events:
    def __init__(self, path: Path, run_id: str):
        self.path, self.run_id = path, run_id
        self.lock = threading.Lock()
        self.sequence = 0
        self.secrets = [v for k, v in os.environ.items()
                        if len(v) >= 8 and any(word in k.upper() for word in ("KEY", "TOKEN", "PASSWORD", "SECRET"))]

    def clean(self, value):
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[REDACTED]")
            return value
        if isinstance(value, dict):
            return {k: self.clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.clean(v) for v in value]
        return value

    def emit(self, kind: str, **fields):
        with self.lock:
            # Parent and worker append sequentially to the same file.
            incomplete = False
            if self.path.exists():
                text = self.path.read_text(encoding="utf-8", errors="replace")
                incomplete = bool(text) and not text.endswith("\n")
                for line in reversed(text.splitlines()):
                    try:
                        self.sequence = max(self.sequence, json.loads(line)["sequence"])
                        break
                    except (json.JSONDecodeError, KeyError):
                        continue  # hard termination may leave a partial final event
            self.sequence += 1
            record = self.clean({"run_id": self.run_id, "sequence": self.sequence,
                                 "time": time.time(), "event": kind, **fields})
            with self.path.open("a", encoding="utf-8") as stream:
                if incomplete:
                    stream.write("\n")
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")


class ScopedTool(Tool):
    def __init__(self, inner: Tool, workspace: Path, allowed_files: list[str], events: Events, test_timeout: int):
        self.inner, self.workspace = inner, workspace.resolve()
        self.allowed_files, self.events, self.test_timeout = set(allowed_files), events, test_timeout
        self.name, self.description, self.parameters = inner.name, inner.description, inner.parameters
        self.read_receipts = []

    def execute(self, **kwargs) -> str:
        started = time.perf_counter()
        self.events.emit("tool_started", tool=self.name, arguments=kwargs)
        try:
            inspect.signature(self.inner.execute).bind(**kwargs)
            if self.name == "bash":
                if kwargs["command"].strip() != VISIBLE_COMMAND:
                    raise ValueError(f"Only the declared visible-test command is permitted: {VISIBLE_COMMAND}")
                folder = self.workspace / ".eval-logs"
                folder.mkdir(exist_ok=True)
                result = run_tests(self.workspace, "tests", min(self.test_timeout, max(1, int(kwargs.get("timeout", 120)))),
                                   folder, f"visible-{uuid.uuid4().hex[:10]}")
                output = (folder / result["stdout"]).read_text(encoding="utf-8", errors="replace")
                output += (folder / result["stderr"]).read_text(encoding="utf-8", errors="replace")
                output = output[:12000] + f"\n[exit code: {result['returncode']}; timed_out: {result['timed_out']}]"
            else:
                args = dict(kwargs)
                if self.name == "glob" and (Path(args["pattern"]).is_absolute() or ".." in Path(args["pattern"]).parts):
                    raise ValueError("Glob pattern must stay inside workspace")
                if self.name in {"read_file", "write_file", "edit_file", "glob", "grep"}:
                    key = "file_path" if self.name.endswith("file") else "path"
                    target = Path(args.get(key, ".")).expanduser()
                    target = (target if target.is_absolute() else self.workspace / target).resolve()
                    if not target.is_relative_to(self.workspace):
                        raise ValueError("Path escapes task workspace")
                    if self.name in {"write_file", "edit_file"} and target.relative_to(self.workspace).as_posix() not in self.allowed_files:
                        raise ValueError("Only allowed source files can be modified")
                    # Block links even when their destination happens to be inside this task.
                    if any(p.is_symlink() for p in self.workspace.rglob("*")):
                        raise ValueError("Symlinks are not supported in fixture workspaces")
                    args[key] = str(target)
                output = self.inner.execute(**args)
        except Exception as exc:  # noqa: BLE001 - tool failures are returned to the agent
            output = f"Error: {type(exc).__name__}: {exc}"
        output = self.events.clean(output)
        if self.name == "read_file" and not output.startswith("Error:"):
            try:
                data = target.read_bytes()
                lines = data.decode("utf-8").splitlines()
                full = "\n".join(f"{index + 1}\t{line}" for index, line in enumerate(lines)) or "(empty file)"
                if output == full and kwargs.get("offset", 1) == 1:
                    self.read_receipts.append({"path": target.relative_to(self.workspace).as_posix(),
                                               "content_hash": hashlib.sha256(data).hexdigest(),
                                               "response": output, "lines": lines})
            except (OSError, UnicodeError):
                pass  # A failed or changed read cannot authorize context replacement.
        self.events.emit("tool_finished", tool=self.name, result=output, seconds=round(time.perf_counter() - started, 4))
        return output


def make_tools(workspace: Path, allowed_files: list[str], events: Events, timeout: int,
               config: RunConfig | None = None) -> list[Tool]:
    # Construct instances, never mutate the module-level ALL_TOOLS collection.
    tools = [ScopedTool(cls(), workspace, allowed_files, events, timeout)
             for cls in (ReadFileTool, GlobTool, GrepTool, EditFileTool, WriteFileTool, TodoWriteTool, BashTool)]
    if config is not None and config.search_backend != "off":
        search = SearchCodeTool(workspace, allowed_files, config.search_backend, config.search_max_chars, events.emit,
                                deduplicate_history=config.search_history == "deduplicate")
        tools.append(ScopedTool(search, workspace, allowed_files, events, timeout))
    return tools


class BudgetLLM:
    def __init__(self, inner, config: RunConfig, events: Events):
        self.inner, self.config, self.events = inner, config, events
        self.model = inner.model
        self.calls = 0
        self.spent = 0
        self.prompt_known = 0
        self.completion_known = 0
        self.missing_usage = 0

    def chat(self, messages, tools=None, **kwargs):
        breakdown = request_breakdown(messages, tools)
        request_estimate = breakdown["request_estimate"]
        reservation = request_estimate + self.config.max_output_tokens
        self.events.emit("request_preflight", next_call=self.calls + 1, **breakdown,
                         spent=self.spent, reservation=reservation, remaining=self.config.token_budget - self.spent,
                         token_budget=self.config.token_budget, context_tokens=self.config.context_tokens)
        if self.spent + reservation > self.config.token_budget:
            self.events.emit("budget_blocked", reason="cumulative_preflight", request_estimate=request_estimate,
                             reservation=reservation, remaining=self.config.token_budget - self.spent)
            raise BudgetExceeded("Insufficient estimated token budget for another request")
        if reservation > self.config.context_tokens:
            self.events.emit("budget_blocked", reason="context_preflight", request_estimate=request_estimate,
                             reservation=reservation, context_tokens=self.config.context_tokens)
            raise BudgetExceeded("Estimated request plus output reservation exceeds context window")
        self.calls += 1
        call_id = f"llm-{self.calls}"
        started = time.perf_counter()
        self.events.emit("llm_started", call_id=call_id, request_estimate=request_estimate, message_count=len(messages))
        try:
            response = self.inner.chat(messages, tools=tools, **kwargs)
        except Exception as exc:
            self.events.emit("llm_failed", call_id=call_id, error=f"{type(exc).__name__}: {exc}")
            raise
        known = response.prompt_tokens > 0 and response.completion_tokens > 0
        if known:
            self.prompt_known += response.prompt_tokens
            self.completion_known += response.completion_tokens
            self.spent += response.prompt_tokens + response.completion_tokens
        else:
            self.missing_usage += 1
            # Missing provider usage is unknown, not a measured zero. Reserve conservatively.
            self.spent += reservation
        self.events.emit("llm_finished", call_id=call_id, seconds=round(time.perf_counter() - started, 4),
                         usage_known=known, prompt_tokens=response.prompt_tokens if known else None,
                         completion_tokens=response.completion_tokens if known else None,
                         tools=[tc.name for tc in response.tool_calls])
        if self.spent > self.config.token_budget:
            self.events.emit("budget_blocked", reason="returned_usage", spent=self.spent,
                             token_budget=self.config.token_budget)
            raise BudgetExceeded("Returned usage exceeds task budget; no further tool execution")
        return response

    def metrics(self) -> dict:
        return {"llm_calls": self.calls, "prompt_tokens": self.prompt_known if not self.missing_usage else None,
                "completion_tokens": self.completion_known if not self.missing_usage else None,
                "known_prompt_tokens": self.prompt_known, "known_completion_tokens": self.completion_known,
                "missing_usage_calls": self.missing_usage, "budget_accounted_tokens": self.spent,
                "budget_enforcement": "estimated preflight + returned usage; not a provider billing hard cap",
                "cost_usd": None, "failed_provider_attempt_usage": "unknown"}
