"""One CoreCoder agent per process. Receives no target tests or live-mode oracle."""

import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from corecoder import LLM, Agent
from corecoder.demo import ScriptedLLM
from corecoder.llm import LLMResponse, ToolCall
from corecoder.permissions import Permission

from .context_policy import covered_search_view, duplicate_read_view, windowed_read_view
from .contract_feedback import run_contract_feedback
from .fixed_evidence import diagnose
from .pipeline import run_pipeline
from .prompts import repair_prompt
from .runtime import VISIBLE_COMMAND, BudgetExceeded, BudgetLLM, Events, make_tools
from .schema import RunConfig


def ollama_metadata(config: RunConfig) -> dict | None:
    endpoint = urlparse(config.base_url)
    if endpoint.hostname not in {"localhost", "127.0.0.1", "::1"} or endpoint.port != 11434:
        return None
    base = f"{endpoint.scheme}://{endpoint.netloc}"
    result = {}
    for name, route, data in (("version", "/api/version", None),
                              ("model", "/api/show", {"model": config.model}),
                              ("identity", "/api/tags", None), ("loaded", "/api/ps", None)):
        try:
            body = json.dumps(data).encode() if data else None
            with urlopen(Request(base + route, data=body, headers={"Content-Type": "application/json"}), timeout=5) as stream:
                info = json.load(stream)
            if name == "model":
                info = {key: info.get(key) for key in ("details", "capabilities", "parameters")}
            elif name == "identity":
                info = {'models': [{'name': model.get('name'), 'digest': model.get('digest')}
                                   for model in info.get('models', [])
                                   if model.get('name', model.get('model')) == config.model]}
            result[name] = info
        except Exception as exc:  # noqa: BLE001 - optional runtime metadata cannot abort a task
            result[name] = {"error_type": type(exc).__name__}
    return result


class TracedLLM(LLM):
    def __init__(self, *args, events: Events, **kwargs):
        super().__init__(*args, **kwargs)
        self.events = events
        self.client.max_retries = 0  # retain only CoreCoder's declared retry layer

    def chat(self, messages, tools=None, on_token=None, on_reasoning=None, response_format=None, max_tokens=None):
        # A worker makes sequential calls; scope the format to this request only.
        previous = self.extra
        if response_format is not None:
            self.extra = {**previous, "response_format": response_format}
        if max_tokens is not None:
            self.extra = {**self.extra, 'max_tokens': max_tokens}
            self.extra.pop('max_completion_tokens', None)
        try:
            return super().chat(messages, tools=tools, on_token=on_token, on_reasoning=on_reasoning)
        finally:
            self.extra = previous

    def _drain(self, stream, on_token, on_reasoning):
        def observe():
            seen = set()
            for chunk in stream:
                model = getattr(chunk, "model", None)
                if model and model not in seen:
                    seen.add(model)
                    self.events.emit("provider_model", model=model)
                for choice in getattr(chunk, "choices", []):
                    reason = getattr(choice, "finish_reason", None)
                    if reason:
                        self.events.emit("provider_finish_reason", reason=reason)
                yield chunk

        return super()._drain(observe(), on_token, on_reasoning)


class FixtureAgent(Agent):
    """Keep side effects in call order, including read/edit/test combinations."""

    def _full_messages(self):
        if getattr(self, 'context_events', None) is not None:
            self.task_round = getattr(self, 'task_round', 0) + 1
            self.context_events.emit('agent_round', round=self.task_round)
        for tool in self.tools:
            inner = getattr(tool, "inner", tool)
            if tool.name == "search_code":
                inner.sync_history(self.messages)
        messages = super()._full_messages()
        if getattr(self, "evidence_policy", "none") == "read-cover":
            receipts = [receipt for tool in self.tools for receipt in getattr(tool, "read_receipts", [])]
            messages, stats = covered_search_view(messages, self.evidence_workspace, receipts)
            self.context_events.emit("context_organized", policy="read-cover", **stats)
        if getattr(self, 'evidence_policy', 'none') == 'read-dedup':
            receipts = [receipt for tool in self.tools for receipt in getattr(tool, 'fragment_receipts', [])]
            messages, stats = duplicate_read_view(messages, self.evidence_workspace, receipts)
            self.context_events.emit('context_organized', policy='read-dedup', **stats)
        if getattr(self, 'evidence_policy', 'none') == 'read-window':
            messages, stats = windowed_read_view(messages)
            self.context_events.emit('context_organized', policy='read-window', **stats)
        return messages

    def _exec_tools_parallel(self, tool_calls, on_tool=None):
        results = []
        for tc in tool_calls:
            if on_tool:
                on_tool(tc.name, tc.arguments)
            result = self._pre_hooks(tc) or self._permit(tc)
            if result is None:
                result = self._exec_tool(tc)
                self._post_hooks(tc, result)
            results.append(result)
        return results


def scripted_llm(job: dict) -> ScriptedLLM:
    # Deliberately oracle-assisted harness test, NEVER a model benchmark.
    turns = []
    if job["config"].get("search_backend", "off") != "off":
        turns.append(LLMResponse(tool_calls=[ToolCall("search", "search_code", {"query": "contract contracts", "top_k": 3})]))
    for i, edit in enumerate(job["oracle_edits"]):
        turns.append(LLMResponse(tool_calls=[ToolCall(f"read-{i}", "read_file", {"file_path": edit["file"]})]))
        turns.append(LLMResponse(tool_calls=[ToolCall(f"edit-{i}", "edit_file", {
            "file_path": edit["file"], "old_string": edit["old"], "new_string": edit["new"],
        })]))
    turns.append(LLMResponse(tool_calls=[ToolCall("test", "bash", {
        "command": job.get("visible_command", VISIBLE_COMMAND)})]))
    turns.append(LLMResponse(content="Scripted oracle repair completed; independent verification is still required."))
    return ScriptedLLM(turns, model="scripted-oracle")


def main(job_path: Path) -> int:
    job = json.loads(job_path.read_text(encoding="utf-8"))
    config = RunConfig(**job["config"])
    root = job_path.parent
    events = Events(root / "trace.jsonl", job["run_id"])
    result = {"status": "agent_error", "final_message": "", "metrics": None}
    counted = None
    try:
        workspace = Path(job["workspace"]).resolve()
        os.chdir(workspace)
        tools = make_tools(workspace, job["allowed_files"], events, config.test_timeout, config)
        if "real_visible_python" in job:
            from .real_tasks import configure_visible_tools

            configure_visible_tools(tools, workspace, job["real_visible_python"])
        events.emit("worker_started", mode=config.mode, model=config.model)
        if config.mode == "scripted":
            llm = scripted_llm(job)
        else:
            local = urlparse(config.base_url).hostname in {"localhost", "127.0.0.1", "::1"}
            key = (os.getenv("CORECODER_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
                   or ("ollama" if local else ""))
            if not key:
                raise ValueError("No API key configured for the requested remote endpoint")
            extra = {"temperature": config.temperature, "max_tokens": config.max_output_tokens,
                     "timeout": min(60, config.wall_timeout)}
            if config.reasoning_effort:
                extra["reasoning_effort"] = config.reasoning_effort
            result["ollama_before"] = ollama_metadata(config)
            counted = BudgetLLM(TracedLLM(config.model, key, config.base_url, events=events, **extra), config, events)
            llm = counted
        if config.mode == "fixed-evidence":
            result.update(diagnose(llm, workspace, job["description"], job["allowed_files"], events))
            return 0
        if config.mode == "pipeline":
            result.update(run_pipeline(llm, workspace, job["description"], job["allowed_files"], config, events))
            return 0
        if config.mode == "contract-feedback":
            result.update(run_contract_feedback(llm, workspace, job["description"], job["allowed_files"], config, events))
            return 0
        if job.get("workflow") == "staged":
            from .real_admission import execute
            from .staged_repair import run_staged

            if config.mode != "live":
                raise ValueError("Staged repair requires live mode")
            result.update(run_staged(llm, workspace, job["description"], job["allowed_files"], config, events,
                                     lambda logs: execute(workspace, workspace / ".real-visible", "Controls", logs,
                                                          Path(job["real_visible_python"]), config.test_timeout),
                                     evidence_policy=job.get("staged_evidence_policy", "read-first")))
            return 0
        if job.get("workflow") in {"symbol-patch", "symbol-feedback"}:
            from .symbol_patch import run_symbol_patch

            if config.mode != "live":
                raise ValueError("Symbol patch worker requires live mode")
            if job["workflow"] == "symbol-feedback":
                from .symbol_feedback import run_symbol_feedback

                result.update(run_symbol_feedback(llm, workspace, job["description"], job["allowed_files"],
                                                   config, events, job["real_visible_python"]))
                return 0
            result.update(run_symbol_patch(llm, workspace, job["description"], job["allowed_files"], config, events,
                                            prompt_policy=job.get("symbol_prompt_policy", "baseline"),
                                            context_policy=job.get("symbol_context_policy", "base")))
            return 0
        agent = FixtureAgent(llm=llm, tools=tools, permission=Permission(allow_all=True),
                      max_rounds=config.max_rounds, max_context_tokens=config.context_tokens)
        agent.evidence_policy, agent.evidence_workspace, agent.context_events = config.context_policy, workspace, events
        agent._todo = next(tool.inner for tool in tools if tool.name == "todo_write")
        prompt = repair_prompt(job["description"], job["allowed_files"], config.search_backend, config.prompt_policy,
                               job.get("visible_command", VISIBLE_COMMAND))
        result["prompt_hash"] = hashlib.sha256((agent._system + "\n" + prompt).encode()).hexdigest()
        normalized_prompt = (agent._system + "\n" + prompt).replace(str(workspace), "<TASK_WORKSPACE>")
        result["protocol_prompt_hash"] = hashlib.sha256(normalized_prompt.encode()).hexdigest()
        result["tool_schema_hash"] = hashlib.sha256(json.dumps(agent._tool_schemas(), sort_keys=True).encode()).hexdigest()
        answer = agent.chat(prompt)
        result.update(status="round_limit" if answer == "(reached maximum tool-call rounds)" else "completed",
                      final_message=answer)
    except BudgetExceeded as exc:
        result.update(status="budget_exceeded", error=str(exc))
    except Exception as exc:  # noqa: BLE001 - persist worker errors for independent grading
        result.update(error=f"{type(exc).__name__}: {exc}")
    finally:
        if counted:
            result["metrics"] = counted.metrics()
            result["ollama_after"] = ollama_metadata(config)
        events.emit("worker_finished", status=result["status"])
        (root / "worker-result.json").write_text(json.dumps(events.clean(result), ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]).resolve()))
