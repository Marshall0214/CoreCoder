"""Shared pytest fixtures and helpers."""

from corecoder.tools import ALL_TOOLS

import os
from pathlib import Path

# 将 pytest 临时根目录重定向到项目内的 .pytest_tmp 文件夹
_TEMP_ROOT = Path(__file__).parent / ".pytest_tmp"
_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(_TEMP_ROOT))

def get_tool(name: str):
    """Look up a tool by name."""
    for t in ALL_TOOLS:
        if t.name == name:
            return t
    return None
