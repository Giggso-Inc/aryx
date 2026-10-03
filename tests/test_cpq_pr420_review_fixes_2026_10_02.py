"""PR 420 review fixes: session untouched after a post-loop timeout (M1), executor
saturation and timeout ordering (M2), all-empty table scan not cached (M3),
bounded rule-trace breaker state (N4), no LLM result text at INFO (N5)."""
from __future__ import annotations

import logging
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from aryx.api.ask_turn_steps import post_loop_executor as ple
from aryx.api.ask_turn_steps.ask_step10_recompute_pending import _step10_recompute_pending
from aryx.config import get_settings
from aryx.cpq.data_table import data_table_loader as ldr
from aryx.store import rule_trace_store as rts


@pytest.fixture(autouse=True)
def _restore_settings():
    s = get_settings()
    prev = (s.cpq_post_loop_timeout_enabled, s.cpq_post_loop_timeout_s)
    yield
    s.cpq_post_loop_timeout_enabled, s.cpq_post_loop_timeout_s = prev


# ---- M1: bounded call works on copies; merged back only on success ----------
def _session():
    return SimpleNamespace(
        filled={}, filled_source={"a": "user"}, filled_multi={"m": ["x"]}, country=None,
        pending_grid_declined_vns=set(), model_leaf_resolved=False,
    )


def _engine(fill):
    eng = MagicMock()
    eng.evaluate_rules_loop.side_effect = lambda *a, **k: ([], {}, {}, {})
    eng.auto_fill.side_effect = fill
    eng.append_pending_grid_quantities.side_effect = lambda p, *a, **k: p
    return eng


def _call(eng, session):
    req = SimpleNamespace(workspace_id=1)
    with patch("aryx.api.ask_api._cpq_engine", eng), \
         patch("aryx.api.ask_turn_steps.ask_step10_recompute_pending.grid_narrow_kwargs",
               return_value={}):
        return _step10_recompute_pending(
            {}, [], session, [], [], [], None, {}, set(), set(), [], req, "")


def test_timeout_leaves_session_untouched_even_if_orphan_keeps_writing():
    s = get_settings()
    s.cpq_post_loop_timeout_enabled = True
    s.cpq_post_loop_timeout_s = 0.2
    release = threading.Event()
    done = threading.Event()

    def slow_fill(*a, **kw):
        kw["filled_source"]["orphan"] = "written-after-504"      # in-place, like auto_fill
        kw["already_filled_multi"]["m"].append("late")
        release.wait(5)
        done.set()
        return {}, {}, []

    sess = _session()
    try:
        with pytest.raises(HTTPException) as ei:
            _call(_engine(slow_fill), sess)
        assert ei.value.status_code == 504
        release.set()
        assert done.wait(5)
    finally:
        release.set()
    assert sess.filled_source == {"a": "user"}
    assert sess.filled_multi == {"m": ["x"]}


def test_success_merges_copies_back_into_session():
    s = get_settings()
    s.cpq_post_loop_timeout_enabled = True
    s.cpq_post_loop_timeout_s = 5.0

    def fill(*a, **kw):
        kw["filled_source"]["b"] = "rule"
        kw["already_filled_multi"]["m"].append("y")
        return {}, {}, []

    sess = _session()
    src, multi = sess.filled_source, sess.filled_multi
    _call(_engine(fill), sess)
    assert sess.filled_source == {"a": "user", "b": "rule"}
    assert sess.filled_multi == {"m": ["x", "y"]}
    assert sess.filled_source is src and sess.filled_multi is multi   # same objects, updated in place


def test_flag_off_passes_the_live_session_dicts():
    get_settings().cpq_post_loop_timeout_enabled = False
    seen = {}

    def fill(*a, **kw):
        seen["src"] = kw["filled_source"]
        seen["multi"] = kw["already_filled_multi"]
        return {}, {}, []

    sess = _session()
    _call(_engine(fill), sess)
    assert seen["src"] is sess.filled_source and seen["multi"] is sess.filled_multi


# ---- M2: saturation rejects instead of queueing; ordering warning ------------
def test_saturated_pool_rejects_with_503_and_does_not_queue():
    release = threading.Event()
    results = []

    def blocker():
        release.wait(5)
        return 1

    def submit():
        try:
            results.append(ple.run_post_loop_bounded(blocker, 0.2))
        except HTTPException as exc:
            results.append(exc.status_code)

    threads = []
    try:
        for _ in range(ple._POST_LOOP_MAX_WORKERS):
            t = threading.Thread(target=submit)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=5)
        # every worker is now abandoned (504 returned, thread still running)
        assert results.count(504) == ple._POST_LOOP_MAX_WORKERS
        with pytest.raises(HTTPException) as ei:
            ple.run_post_loop_bounded(lambda: 1, 5)
        assert ei.value.status_code == 503
    finally:
        release.set()
        for _ in range(100):
            if ple._inflight == 0:
                break
            threading.Event().wait(0.05)
    assert ple._inflight == 0
    assert ple.run_post_loop_bounded(lambda: 7, 5) == 7        # recovers once workers finish


def test_defaults_keep_the_documented_timeout_ordering():
    fields = type(get_settings()).model_fields
    rdb = fields["cpq_rdb_call_timeout_ms"].default / 1000.0
    lock = fields["cpq_tables_cache_lock_timeout_s"].default
    post = fields["cpq_post_loop_timeout_s"].default
    assert rdb < lock < post


def test_inverted_ordering_warns_once(caplog):
    ple._ordering_warned = False
    cfg = SimpleNamespace(cpq_post_loop_timeout_s=30.0, cpq_rdb_call_timeout_ms=60000,
                          cpq_tables_cache_lock_timeout_s=90.0)
    with caplog.at_level(logging.WARNING, logger=ple.logger.name):
        ple.warn_if_timeouts_inverted(cfg)
        ple.warn_if_timeouts_inverted(cfg)
    assert sum("not above" in r.getMessage() for r in caplog.records) == 1
    ple._ordering_warned = False
    ok = SimpleNamespace(cpq_post_loop_timeout_s=120.0, cpq_rdb_call_timeout_ms=60000,
                         cpq_tables_cache_lock_timeout_s=90.0)
    with caplog.at_level(logging.WARNING, logger=ple.logger.name):
        caplog.clear()
        ple.warn_if_timeouts_inverted(ok)
    assert not caplog.records
    ple._ordering_warned = False


# ---- M3: an all-empty scan is not stored in the module cache -----------------
class _Rdb:
    def __init__(self, grouped):
        self.grouped = grouped

    def fetch_all_entities_grouped_by_type(self, workspace_id):
        return self.grouped


def _scan(grouped):
    ldr._TABLES_CACHE.clear()
    per_turn: dict = {}
    with patch.object(ldr, "get_cpq_rdb", return_value=_Rdb(grouped)), \
         patch.object(ldr, "_invalidate_on_marker_change", return_value=None):
        ldr._load_all_tables(1, "p", per_turn)
    return per_turn


def test_all_empty_scan_is_not_stored_in_module_cache_but_is_in_per_turn_cache(caplog):
    with caplog.at_level(logging.WARNING, logger=ldr.logger.name):
        per_turn = _scan({})
    assert not ldr._TABLES_CACHE
    assert (1, "p") in per_turn                      # still memoised for this turn only
    assert any("not stored in the module cache" in r.getMessage() for r in caplog.records)
    ldr._TABLES_CACHE.clear()


def test_non_empty_scan_is_stored_in_module_cache():
    _scan({"Whitelist": [(1, {"CPQModel": "M", "BaseModel": "B", "attr1": "a", "val1": "v"})]})
    assert ldr._TABLES_CACHE
    ldr._TABLES_CACHE.clear()


# ---- N4: breaker state is capped --------------------------------------------
def test_breaker_state_is_capped_and_evicts_oldest():
    rts._fail_counts.clear()
    rts._open_runs.clear()
    try:
        for i in range(rts._MAX_TRACKED_RUNS + 50):
            rts.RuleTraceStore._record_failure(f"run-{i}", 1)   # threshold 1: opens immediately
        assert len(rts._fail_counts) <= rts._MAX_TRACKED_RUNS
        assert len(rts._open_runs) <= rts._MAX_TRACKED_RUNS
        assert "run-0" not in rts._open_runs                     # oldest evicted
        assert f"run-{rts._MAX_TRACKED_RUNS + 49}" in rts._open_runs
    finally:
        rts._fail_counts.clear()
        rts._open_runs.clear()


# ---- N5: LLM result text never at INFO --------------------------------------
def test_tier2_info_log_has_no_result_text(caplog):
    from aryx.cpq.bml.bml import BmlEvaluator

    ev = BmlEvaluator.__new__(BmlEvaluator)
    ev._run_id, ev._workspace_id = "r1", 1
    ev.stats = {"prompt_tokens": 0, "completion_tokens": 0, "durable_hit": 0}
    ev._durable_key = lambda *a, **k: "k"
    ev._durable_get = lambda k: (None, False)
    ev._durable_put = lambda *a, **k: None
    ev._evaluate_llm = lambda script, variables: ["SECRET-CUSTOMER-VALUE"]
    with caplog.at_level(logging.INFO, logger="aryx.cpq.bml.bml"):
        ev._call_tier2("values", "script", {"a": "b"}, None)
    info = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.INFO)
    assert "bml_tier2: result" in info
    assert "SECRET-CUSTOMER-VALUE" not in info
    with caplog.at_level(logging.DEBUG, logger="aryx.cpq.bml.bml"):
        caplog.clear()
        ev._call_tier2("values", "script2", {"a": "b"}, None)
    debug = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG)
    assert "SECRET-CUSTOMER-VALUE" in debug
