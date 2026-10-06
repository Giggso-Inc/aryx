"""Every caller of `_cpq_summary_text` passes `filled_multi` (PR review M1 follow-up).

A source scan, so a new caller that forgets the argument fails here instead of silently
reading a multi-select that lives only in `session.filled_multi` as unfilled."""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "aryx"


def _calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if name == "_cpq_summary_text":
                yield node


def test_every_summary_caller_passes_filled_multi():
    missing, seen = [], 0
    for path in SRC.rglob("*.py"):
        if path.name == "ask_cpq_summary_text.py" or ".raven" in path.parts:
            continue
        for call in _calls(path):
            seen += 1
            if "filled_multi" not in {k.arg for k in call.keywords}:
                missing.append(f"{path.relative_to(SRC)}:{call.lineno}")
    assert seen >= 11
    assert not missing, f"callers without filled_multi: {missing}"
