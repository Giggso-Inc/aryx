"""Where one `auto_fill` pass spends its time (logging only, no behaviour).

ws 1267 dev log: an `auto_fill` pass takes 60 to 245 s (45 of 112 passes over two minutes) and a turn runs two to four of them plus
a post-loop pass, so a turn can pass 15 minutes. `cpq_perf: auto_fill took` times the whole pass and says nothing about which
stage or which attribute is slow. This collects, per pass, seconds per stage and per attribute, and the time spent outside the
stages (the DEBUG stage-trail logging, the setup and the post-passes), and writes ONE `cpq_perf: auto_fill stages` INFO line."""
from __future__ import annotations

import contextvars
import time
from collections import Counter, defaultdict
from typing import Any


class StageTimer:
    """Seconds per stage (and per attribute) for one `auto_fill` call."""

    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.stage_s: dict[str, float] = defaultdict(float)
        self.stage_calls: Counter = Counter()
        self.attr_s: dict[str, float] = defaultdict(float)       # whole resolve_one_attr, per attribute
        self.attr_stage_s: dict[str, float] = defaultdict(float)  # the stages only, per attribute
        self.attrs = 0

    def add_stage(self, stage: str, seconds: float) -> None:
        self.stage_s[stage] += seconds
        self.stage_calls[stage] += 1

    def add_attr(self, vn: str, total_s: float, stages_s: float) -> None:
        self.attrs += 1
        self.attr_s[vn] += total_s
        self.attr_stage_s[vn] += stages_s


_CURRENT: contextvars.ContextVar[StageTimer | None] = contextvars.ContextVar("cpq_auto_fill_stage_timer", default=None)


def begin() -> tuple[StageTimer, contextvars.Token]:
    timer = StageTimer()
    return timer, _CURRENT.set(timer)


def end(token: contextvars.Token) -> None:
    _CURRENT.reset(token)


def current() -> StageTimer | None:
    return _CURRENT.get()


def summary_line(timer: StageTimer, pass_no: Any = None, top_stages: int = 8, top_attrs: int = 6) -> str:
    """One INFO line: total, time inside the attribute loop, time outside it (setup and post-passes), the logging overhead of
    the stage trail (attribute time minus its stages' time), the slowest stages and the slowest attributes."""
    total = time.perf_counter() - timer.started
    in_attrs = sum(timer.attr_s.values())
    in_stages = sum(timer.stage_s.values())
    stages = " ".join(f"{name}={sec:.1f}s/{timer.stage_calls[name]}"
                      for name, sec in sorted(timer.stage_s.items(), key=lambda kv: -kv[1])[:top_stages])
    slow = " ".join(f"{vn}={sec:.2f}s"
                    for vn, sec in sorted(timer.attr_s.items(), key=lambda kv: -kv[1])[:top_attrs])
    return (f"cpq_perf: auto_fill stages pass={pass_no} total={total:.1f}s attrs={timer.attrs} in_attrs={in_attrs:.1f}s "
            f"outside_attrs={max(total - in_attrs, 0.0):.1f}s trace_overhead={max(in_attrs - in_stages, 0.0):.1f}s "
            f"stages=[{stages}] slowest_attrs=[{slow}]")
