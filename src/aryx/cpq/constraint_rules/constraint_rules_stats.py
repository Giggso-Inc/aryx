"""Timing stats for LLM-backed constraint script evaluation (#358/#367).

Pure observability: a fresh ``ScriptEvalStats`` is created per
``apply_constraint_rules`` call so nothing accumulates across calls.
"""
from __future__ import annotations

import time
from typing import Any, Callable


class ScriptEvalStats:
    """Counts and cumulative seconds for one kind of script evaluation."""

    __slots__ = ("count", "seconds")

    def __init__(self) -> None:
        self.count = 0
        self.seconds = 0.0

    def timed(self, fn: Callable[..., Any], *args: Any) -> Any:
        """Call ``fn(*args)``, recording one run and its duration."""
        self.count += 1
        t0 = time.monotonic()
        try:
            return fn(*args)
        finally:
            self.seconds += time.monotonic() - t0
