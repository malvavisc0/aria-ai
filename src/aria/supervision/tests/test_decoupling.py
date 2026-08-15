"""Static guard: supervision core stays UI-agnostic."""

from __future__ import annotations

import ast
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]


def _chainlit_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    hits: list[str] = []
    for node in ast.walk(tree):
        mods: list[str] = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods = [node.module]
        hits.extend(m for m in mods if m == "chainlit" or m.startswith("chainlit."))
    return hits


def test_no_chainlit_import_in_supervision_core():
    failures = [
        f"{p.name}: {m}" for p in CORE.glob("*.py") for m in _chainlit_imports(p)
    ]
    assert not failures, failures
