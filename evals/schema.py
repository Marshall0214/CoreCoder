"""Validated task and budget contracts for the initial trusted-fixture suite."""

import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath


def relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError(f"Expected a portable relative path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"Unsafe relative path: {value!r}")
    return value


@dataclass(frozen=True)
class Task:
    task_id: str
    title: str
    description: str
    allowed_files: tuple[str, ...]
    root: Path

    @classmethod
    def load(cls, path: Path) -> "Task":
        path = path.resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", data["task_id"]):
            raise ValueError("Invalid task_id")
        allowed = tuple(relative_path(p) for p in data["allowed_files"])
        if not allowed or len(set(allowed)) != len(allowed):
            raise ValueError("allowed_files must be nonempty and unique")
        for directory in ("workspace", "hidden_tests"):
            root = path.parent / directory
            if not root.is_dir() or root.is_symlink():
                raise ValueError(f"Missing or linked {directory}")
            if any(p.is_symlink() for p in root.rglob("*")):
                raise ValueError("Task fixtures cannot contain symlinks")
        for name in allowed:
            candidate = path.parent / "workspace" / name
            if not candidate.is_file() or not name.endswith(".py") or name.startswith("tests/"):
                raise ValueError(f"Invalid allowed source file: {name}")
        if not list((path.parent / "hidden_tests").glob("test_*.py")):
            raise ValueError("Task must have independent target tests")
        return cls(data["task_id"], data["title"], data["description"], allowed, path.parent)


@dataclass(frozen=True)
class RunConfig:
    mode: str = "unchanged"
    model: str = "deepseek-flash"
    base_url: str = "https://api.deepseek.com"
    max_rounds: int = 12
    token_budget: int = 30000
    max_output_tokens: int = 2048
    context_tokens: int = 16000
    wall_timeout: int = 180
    test_timeout: int = 15
    temperature: float = 0.0
    reasoning_effort: str | None = None
    search_backend: str = "off"
    search_max_chars: int = 6000
    search_history: str = "full"
    context_policy: str = "none"
    prompt_policy: str = "baseline"
    evidence_top_k: int = 5
    evidence_dependency_depth: int = 2
    evidence_order: str = "selection"
    patch_policy: str = "baseline"

    def __post_init__(self):
        if self.patch_policy not in {"baseline", "contract-coverage"}:
            raise ValueError("patch_policy must be baseline or contract-coverage")
        if self.mode not in {"pipeline", "contract-feedback"} and self.patch_policy != "baseline":
            raise ValueError("Patch coverage requires pipeline mode")
        if self.evidence_order not in {"selection", "path"}:
            raise ValueError("evidence_order must be selection or path")
        if self.mode not in {"pipeline", "contract-feedback"} and self.evidence_order != "selection":
            raise ValueError("Evidence ordering requires pipeline mode")
        if self.mode not in {"unchanged", "reference", "scripted", "live", "fixed-evidence", "pipeline", "contract-feedback"}:
            raise ValueError("Unknown run mode")
        if self.search_backend not in {"off", "none", "keyword"}:
            raise ValueError("search_backend must be off, none or keyword")
        if self.search_history not in {"full", "deduplicate"}:
            raise ValueError("search_history must be full or deduplicate")
        if self.search_history == "deduplicate" and self.search_backend != "keyword":
            raise ValueError("History deduplication requires keyword search")
        if self.context_policy not in {"none", "read-cover"}:
            raise ValueError("context_policy must be none or read-cover")
        if self.context_policy == "read-cover" and (self.search_backend != "keyword" or self.search_history != "full"):
            raise ValueError("read-cover requires keyword search and full search history")
        if self.prompt_policy not in {"baseline", "contract-check"}:
            raise ValueError("prompt_policy must be baseline or contract-check")
        if self.mode == "fixed-evidence" and (self.search_backend != "off" or self.context_policy != "none"
                                             or self.search_history != "full" or self.prompt_policy != "baseline"):
            raise ValueError("fixed-evidence has a separate protocol; Agent policies must use defaults")
        if self.mode in {"pipeline", "contract-feedback"} and (self.search_backend != "keyword" or self.context_policy != "none"
                                        or self.search_history != "full" or self.prompt_policy != "baseline"):
            raise ValueError("pipeline requires keyword, full search history and baseline Agent policies")
        for name, lower, upper in (("evidence_top_k", 1, 20), ("evidence_dependency_depth", 0, 3)):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or not lower <= value <= upper:
                raise ValueError(f"{name} must be between {lower} and {upper}")
        if not isinstance(self.search_max_chars, int) or isinstance(self.search_max_chars, bool) or not 256 <= self.search_max_chars <= 20000:
            raise ValueError("search_max_chars must be between 256 and 20000")
        for name in ("max_rounds", "token_budget", "max_output_tokens", "context_tokens", "wall_timeout", "test_timeout"):
            if not isinstance(getattr(self, name), int) or isinstance(getattr(self, name), bool) or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_output_tokens >= self.context_tokens:
            raise ValueError("Output reservation must be smaller than context window")
        if not math.isfinite(self.temperature) or self.temperature < 0:
            raise ValueError("temperature must be finite and nonnegative")
        from urllib.parse import urlparse

        endpoint = urlparse(self.base_url)
        if endpoint.scheme not in {"http", "https"} or not endpoint.hostname or endpoint.username or endpoint.password:
            raise ValueError("base_url must be an HTTP(S) endpoint without credentials")

    def to_dict(self) -> dict:
        return asdict(self)


def load_suite(suite: Path, task_ids: list[str] | None = None) -> list[Task]:
    tasks = [Task.load(p) for p in sorted(suite.glob("*/task.json"))]
    ids = [t.task_id for t in tasks]
    if not tasks or len(ids) != len(set(ids)):
        raise ValueError("Suite is empty or has duplicate IDs")
    if task_ids:
        missing = set(task_ids) - set(ids)
        if missing:
            raise ValueError(f"Unknown tasks: {sorted(missing)}")
        tasks = [t for t in tasks if t.task_id in task_ids]
    return tasks
