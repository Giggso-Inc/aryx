"""Post-loop auto_fill bounded executor + shared per-turn _dt_cache
(dev-rv-msi #371/#372)."""
from __future__ import annotations

import logging
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from aryx.api.ask_turn_steps import post_loop_executor as ple
from aryx.api.ask_turn_steps.ask_step10_recompute_pending import _step10_recompute_pending
from aryx.config import get_settings
from aryx.cpq import logging_context
from aryx.llm import llm_runtime_state


@pytest.fixture(autouse=True)
def _flags():
    s = get_settings()
    prev = (s.cpq_post_loop_timeout_enabled, s.cpq_post_loop_timeout_s)
    yield
    s.cpq_post_loop_timeout_enabled, s.cpq_post_loop_timeout_s = prev


def test_executor_returns_result():
    assert ple.run_post_loop_bounded(lambda: 42, 5) == 42


def test_executor_propagates_fn_exception():
    def boom():
        raise ValueError("x")
    with pytest.raises(ValueError):
        ple.run_post_loop_bounded(boom, 5)


def test_executor_raises_504_within_limit(caplog):
    release = threading.Event()
    t0 = time.monotonic()
    with caplog.at_level(logging.ERROR, logger=ple.logger.name):
        with pytest.raises(HTTPException) as ei:
            ple.run_post_loop_bounded(lambda: release.wait(5), 0.2)
    release.set()
    assert ei.value.status_code == 504
    assert time.monotonic() - t0 < 2.0
    assert any("TIMED OUT" in r.getMessage() for r in caplog.records)


def test_executor_runs_with_copied_context():
    llm_runtime_state.reset_turn_usage()
    logging_context.set_run_id("run-abc")
    seen = {}

    def fn():
        seen["usage"] = llm_runtime_state.get_turn_usage()
        seen["run_id"] = logging_context.get_run_id()
        return 1

    ple.run_post_loop_bounded(fn, 5)
    assert seen["run_id"] == "run-abc"
    assert seen["usage"] is not None
    logging_context.set_run_id("")


def _session():
    return SimpleNamespace(
        filled={}, filled_source={}, filled_multi={}, country=None,
        pending_grid_declined_vns=set(), model_leaf_resolved=False,
    )


def _engine(captured):
    eng = MagicMock()

    def loop(*a, **kw):
        captured["loop_cache"] = kw.get("_dt_cache", "absent")
        if isinstance(kw.get("_dt_cache"), dict):
            kw["_dt_cache"][(1, "")] = ("populated",)
        return [], {}, {}, {}

    def fill(*a, **kw):
        captured["fill_cache"] = kw.get("_dt_cache", "absent")
        captured["fill_thread"] = threading.current_thread().name
        return {}, {}, []

    eng.evaluate_rules_loop.side_effect = loop
    eng.auto_fill.side_effect = fill
    eng.append_pending_grid_quantities.side_effect = lambda p, *a, **k: p
    return eng


def _call(eng):
    req = SimpleNamespace(workspace_id=1)
    with patch("aryx.api.ask_api._cpq_engine", eng), \
         patch("aryx.api.ask_turn_steps.ask_step10_recompute_pending.grid_narrow_kwargs",
               return_value={}):
        return _step10_recompute_pending(
            {}, [], _session(), [], [], [], None, {}, set(), set(), [], req, "")


def test_flag_on_shares_one_populated_dt_cache_and_runs_in_pool():
    s = get_settings()
    s.cpq_post_loop_timeout_enabled = True
    s.cpq_post_loop_timeout_s = 5.0
    cap: dict = {}
    _call(_engine(cap))
    assert isinstance(cap["loop_cache"], dict)
    assert cap["fill_cache"] is cap["loop_cache"]
    assert cap["loop_cache"] == {(1, ""): ("populated",)}
    assert cap["fill_thread"].startswith("cpq-post-loop")


def test_flag_off_plain_synchronous_call_no_cache_kwarg():
    get_settings().cpq_post_loop_timeout_enabled = False
    cap: dict = {}
    _call(_engine(cap))
    assert cap["loop_cache"] == "absent"
    assert cap["fill_cache"] == "absent"
    assert cap["fill_thread"] == threading.current_thread().name


def test_flag_on_timeout_surfaces_504_from_step():
    s = get_settings()
    s.cpq_post_loop_timeout_enabled = True
    s.cpq_post_loop_timeout_s = 0.2
    release = threading.Event()
    eng = _engine({})
    eng.auto_fill.side_effect = lambda *a, **k: release.wait(5)
    try:
        with pytest.raises(HTTPException) as ei:
            _call(eng)
    finally:
        release.set()
    assert ei.value.status_code == 504
