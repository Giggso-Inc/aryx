"""Per-stage timing for ``evaluate_rules_loop`` (diagnostic only; results unchanged).

Turns on ws 1267 took 5-10 minutes with the rules-loop passes alone taking 20-90 s each, and the existing per-stage
``cpq_perf`` lines left the biggest stages (hiding rules and their Tier-2 prefetch, the hidden master string, the
auto-fill prefetch) unmeasured. ``stage_done`` logs a stage in the same ``cpq_perf: <stage> took Ns pass=N`` form;
``add_stage`` only accumulates a stage that already logs itself. ``totals_line`` is the one line per turn that answers
"where did the minutes go".
"""
from __future__ import annotations

import time
from typing import Any

from aryx.cpq.engine import logger


def add_stage(state: Any, name: str, t0: float) -> float:
    """Accumulate the time since `t0` under `name` without logging (the caller already logs the stage)."""
    elapsed = time.monotonic() - t0
    state.stage_s[name] = state.stage_s.get(name, 0.0) + elapsed
    return elapsed


def stage_done(state: Any, name: str, t0: float, pass_num: int, detail: str = "") -> float:
    """Accumulate the stage and log it as ``cpq_perf: <name> took Ns pass=N [detail]``."""
    elapsed = add_stage(state, name, t0)
    logger.info("cpq_perf: %s took %.3fs pass=%d%s", name, elapsed, pass_num, f" {detail}" if detail else "")
    return elapsed


def totals_line(state: Any, total_s: float, passes: int) -> str:
    """``cpq_perf: rules_loop stage totals ...`` -- stages ordered by cumulative time, largest first."""
    ordered = sorted(state.stage_s.items(), key=lambda item: -item[1])
    stages = " ".join(f"{name}={seconds:.1f}s" for name, seconds in ordered)
    return f"cpq_perf: rules_loop stage totals passes={passes} total={total_s:.1f}s {stages}".rstrip()
