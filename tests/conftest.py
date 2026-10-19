"""Shared pytest fixtures and helpers."""

import os
from pathlib import Path

import pytest

from corecoder import Config, checkpoints, cli
from corecoder import llm as llm_module
from corecoder.tools import ALL_TOOLS

# 将 pytest 临时根目录重定向到项目内的 .pytest_tmp 文件夹
_TEMP_ROOT = Path(__file__).parent / ".pytest_tmp"
_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(_TEMP_ROOT))

@pytest.fixture(autouse=True)
def _checkpoints_isolated(tmp_path, monkeypatch):
    """Checkpoint persistence must never touch the real ~/.corecoder."""
    monkeypatch.setattr(checkpoints, "CHECKPOINTS_FILE", tmp_path / "checkpoints.json")
    checkpoints.clear()
    yield
    checkpoints.clear()


@pytest.fixture(autouse=True)
def _pricing_isolated(tmp_path, monkeypatch):
    """Cost estimates must never read the real ~/.corecoder/pricing.json."""
    monkeypatch.setattr(llm_module, "PRICING_FILE", tmp_path / "pricing.json")


def get_tool(name: str):
    """Look up a tool by name."""
    for t in ALL_TOOLS:
        if t.name == name:
            return t
    return None


def repl_with(monkeypatch, agent, inputs, config=None):
    """Drive the real REPL with a scripted list of inputs. Returns the config in use."""
    it = iter(inputs)
    monkeypatch.setattr(cli, "pt_prompt", lambda *a, **k: next(it))
    config = config or Config.from_env()
    cli._repl(agent, config)
    return config
