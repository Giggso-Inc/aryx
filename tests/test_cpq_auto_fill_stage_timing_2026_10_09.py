"""Stage timing for `auto_fill` (logging only): where a 60 to 245 s pass spends its time (ws 1267 dev log)."""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aryx.cpq.auto_fill import auto_fill_run
from aryx.cpq.auto_fill_stages import coordinator, stage_timing


def _slow_stage(seconds):
    def stage(engine, attr, ctx, scope, state):
        time.sleep(seconds)
    stage.__name__ = f"stage_{int(seconds * 1000)}ms"
    return stage


def _resolve(timer_on, attrs=("a_astro", "b_astro")):
    ctx = SimpleNamespace(sources={}, filled={}, filled_multi={})
    timer = token = None
    if timer_on:
        timer, token = stage_timing.begin()
    try:
        with patch.object(coordinator, "_STAGES", (_slow_stage(0.02), _slow_stage(0.005))), \
                patch.object(coordinator, "would_log", return_value=False):
            for vn in attrs:
                coordinator.resolve_one_attr(SimpleNamespace(), SimpleNamespace(variable_name=vn), ctx, SimpleNamespace())
    finally:
        if token is not None:
            stage_timing.end(token)
    return timer


def test_without_a_timer_nothing_is_recorded():
    assert _resolve(False) is None and stage_timing.current() is None


def test_each_stage_and_each_attribute_is_timed():
    timer = _resolve(True)
    assert timer.attrs == 2
    assert timer.stage_calls["stage_20ms"] == 2 and timer.stage_calls["stage_5ms"] == 2
    assert timer.stage_s["stage_20ms"] > timer.stage_s["stage_5ms"] > 0
    assert set(timer.attr_s) == {"a_astro", "b_astro"} and all(v >= 0.02 for v in timer.attr_s.values())


def test_the_summary_line_names_the_slowest_stage_and_attribute_and_the_overhead():
    timer = stage_timing.StageTimer()
    timer.add_stage("stage_options", 3.0)
    timer.add_stage("stage_hint", 0.5)
    timer.add_attr("slow_astro", 3.4, 3.0)
    timer.add_attr("fast_astro", 0.2, 0.2)
    line = stage_timing.summary_line(timer, pass_no=2)
    assert line.startswith("cpq_perf: auto_fill stages pass=2 ")
    assert "stage_options=3.0s/1" in line and line.index("stage_options") < line.index("stage_hint")
    assert "slowest_attrs=[slow_astro=3.40s fast_astro=0.20s]" in line
    assert "in_attrs=3.6s" in line and "trace_overhead=0.1s" in line and "attrs=2" in line    # 3.6 s of attributes, 3.5 s of stages


def test_the_wrapper_logs_one_summary_line_per_call_and_returns_the_result():
    with patch.object(auto_fill_run, "_run_auto_fill", return_value=("filled", "display", ["pending"])), \
            patch("aryx.cpq.engine.logger") as log:
        assert auto_fill_run.run_auto_fill(1, x=2) == ("filled", "display", ["pending"])
    assert log.info.call_count == 1 and log.info.call_args.args[0].startswith("cpq_perf: auto_fill stages")
    assert stage_timing.current() is None                          # the timer is cleared again


def test_the_summary_is_logged_and_the_timer_cleared_even_when_the_fill_raises():
    with patch.object(auto_fill_run, "_run_auto_fill", side_effect=RuntimeError("boom")), \
            patch("aryx.cpq.engine.logger") as log:
        with pytest.raises(RuntimeError):
            auto_fill_run.run_auto_fill()
    assert log.info.call_count == 1 and stage_timing.current() is None


def test_a_failing_logger_never_changes_the_fill():
    with patch.object(auto_fill_run, "_run_auto_fill", return_value="ok"), \
            patch("aryx.cpq.engine.logger") as log:
        log.info.side_effect = RuntimeError("logging is down")
        assert auto_fill_run.run_auto_fill() == "ok"
