"""Raven records added while merging dev_oci (44 upstream commits) into feat/ravenlogger.

Covers the new upstream decision points: csv_bml job failure, confirm-job cancel,
post-loop timeout and saturation, DB call timeouts, csv_bml trace correlation,
rule-scope filtering and the resolved-model candidate tier.
"""
from __future__ import annotations

import importlib
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from aryx import raven_log as rl

_MODULES = [
    "aryx.api.file_ingest.file_ingest_run",
    "aryx.api.doc_discover.doc_discover_confirm_job",
    "aryx.api.ask_turn_steps.post_loop_executor",
    "aryx.store.db_timeouts",
    "aryx.cpq.rule_scope",
    "aryx.cpq.data_table_bridge.candidates",
]


@pytest.fixture
def recs(monkeypatch):
    """Capture every record emitted by the modules under test (all levels)."""
    out: list[dict] = []

    def fake(level, criticality, message, **kw):
        out.append({"level": level, "crit": criticality, "message": message,
                    "error_code": kw.get("error_code", ""), "context": kw.get("context") or {},
                    "trace_id": kw.get("trace_id") or rl.current_run_id()})
        return {}

    for name in _MODULES:
        mod = importlib.import_module(name)
        if hasattr(mod, "raven_log"):
            monkeypatch.setattr(mod, "raven_log", fake)
        if hasattr(mod, "would_log"):
            monkeypatch.setattr(mod, "would_log", lambda lv: True)
    rl.bind_run_id("")
    yield out
    rl.bind_run_id("")


def _ev(recs, event):
    return [r for r in recs if r["message"].startswith(event)]


def test_run_files_csv_bml_rejection_is_job_failed_not_completed(recs, monkeypatch):
    from aryx.api.file_ingest import file_ingest_run as run
    from aryx.csv_bml_ingestion import upload_hook

    jobs = MagicMock()
    monkeypatch.setattr(run, "JobStore", lambda dsn: jobs)
    monkeypatch.setattr(run, "DatasourceStore", lambda dsn: MagicMock())
    monkeypatch.setattr(run, "get_settings", lambda: MagicMock(effective_dsn=lambda: "d", csv_chunk_rows=0,
                                                                ingest_relate=False))
    monkeypatch.setattr(run, "_local_broker", lambda: MagicMock())
    monkeypatch.setattr(run, "cpq_layout_upload_active", lambda name: False)
    monkeypatch.setattr(run, "csv_bml_enabled", lambda: True)
    session = MagicMock()
    session.ingest.return_value = SimpleNamespace(status="failed", rows_loaded=0, error_code="CBI_X",
                                                  message="no query for this table")
    monkeypatch.setattr(upload_hook, "CsvBmlUploadSession", lambda ws, job: session)
    run._run_files([(b"a,b\n1,2\n", "t.csv")], "T", ["id"], [], "job-bml", 1)
    assert jobs.finish.call_args.kwargs["status"] == "failed"
    assert not _ev(recs, "ingest.job.completed")
    ev = _ev(recs, "ingest.job.failed")[0]
    assert ev["level"] == "ERROR" and ev["error_code"] == "ARYX_ING_CSV_BML_FAILED"
    assert ev["context"]["impact_scope"]["csv_bml_failed"] == 1 and ev["trace_id"] == "job-bml"


def test_confirm_job_cancel_logs_cancelled_not_failed(recs):
    from aryx.api.doc_discover.doc_discover_confirm_job import _confirm_job
    from aryx.pipeline.orchestrate import PipelineCancelled

    mod = "aryx.api.doc_discover.doc_discover_confirm_job"
    with patch(f"{mod}.JobStore", return_value=MagicMock()), patch(f"{mod}.get_settings"), \
         patch(f"{mod}.discoveries") as disc, patch(f"{mod}._local_broker"), \
         patch(f"{mod}.ingest_confirmed", side_effect=PipelineCancelled("stop")), \
         patch(f"{mod}._reset_discovery_status"):
        disc.get.return_value = {"mentions": [], "tabular": []}
        _confirm_job("did-1", ["A"], [], job_id="job-c", workspace_id=1)
    ev = _ev(recs, "ingest.job.cancelled")[0]
    assert ev["context"]["final_state"] == "cancelled" and ev["context"]["trigger"] == "worker_stop"
    assert ev["trace_id"] == "job-c"
    assert not _ev(recs, "ingest.job.failed")


def test_post_loop_timeout_is_error_with_code(recs):
    from aryx.api.ask_turn_steps import post_loop_executor as ple

    gate = threading.Event()
    with pytest.raises(HTTPException) as err:
        ple.run_post_loop_bounded(lambda: gate.wait(5), 0.05)
    gate.set()
    assert err.value.status_code == 504
    ev = _ev(recs, "ask.post_loop.timed_out")[0]
    assert ev["level"] == "ERROR" and ev["error_code"] == "ARYX_ASK_POST_LOOP_TIMEOUT"
    assert ev["context"]["http_status"] == 504


def test_post_loop_saturation_is_error_with_code(recs, monkeypatch):
    from aryx.api.ask_turn_steps import post_loop_executor as ple

    monkeypatch.setattr(ple, "_inflight", ple._POST_LOOP_MAX_WORKERS)
    with pytest.raises(HTTPException) as err:
        ple.run_post_loop_bounded(lambda: 1, 1)
    assert err.value.status_code == 503
    ev = _ev(recs, "ask.post_loop.saturated")[0]
    assert ev["error_code"] == "ARYX_ASK_POST_LOOP_SATURATED" and ev["context"]["decision"] == "deny"


def test_db_timeout_warns_only_for_timeouts(recs):
    from aryx.store import db_timeouts

    db_timeouts.log_if_timeout(RuntimeError("ORA-03156: Connection timed out"), "cpq rdb(oracle)")
    db_timeouts.log_if_timeout(RuntimeError("ORA-00942: table or view does not exist"), "cpq rdb(oracle)")
    evs = _ev(recs, "db.call.timed_out")
    assert len(evs) == 1 and evs[0]["error_code"] == "ARYX_DB_CALL_TIMEOUT"
    assert evs[0]["context"]["dependency_name"] == "oracle_adb"


def test_db_call_timeout_set_failure_warns(recs):
    from aryx.store import db_timeouts

    class Conn:
        @property
        def call_timeout(self):
            return 0

        @call_timeout.setter
        def call_timeout(self, v):
            raise RuntimeError("read only")

    with db_timeouts.oracle_call_timeout(Conn(), 1000):
        pass
    steps = [r["context"]["step"] for r in _ev(recs, "db.call_timeout.")]
    assert steps == ["set", "restore"]


def test_csv_bml_tracker_uses_bound_job_id():
    from aryx.csv_bml_ingestion.tracking import RunTracker

    rl.bind_run_id("job-xyz")
    try:
        assert RunTracker("t.csv").trace_id == "job-xyz"
    finally:
        rl.bind_run_id("")
    assert RunTracker("t.csv").trace_id not in ("", None, "job-xyz")


def _bound_turn(scope_ids):
    chosen = SimpleNamespace(cpq_model="APX900", node_name="APX 900", base_models=frozenset())
    res = SimpleNamespace(resolved=True, chosen=chosen, scope_node_ids=frozenset(scope_ids))
    return SimpleNamespace(resolution=res, workspace_id=1, catalog_prefix="",
                           first_time=lambda key: True)


def test_rule_scope_filter_logs_kept_counts(recs, monkeypatch):
    from aryx.cpq import rule_scope

    monkeypatch.setattr(rule_scope, "rule_scope_enabled", lambda: True)
    monkeypatch.setattr(rule_scope._model_resolution, "get_turn", lambda: _bound_turn({"10"}))
    monkeypatch.setattr(rule_scope, "_cached_catalog",
                        lambda ws, p: SimpleNamespace(nodes_by_id={"10": 1, "20": 1}))
    rules = [SimpleNamespace(ref_id="10"), SimpleNamespace(ref_id="20"), SimpleNamespace(ref_id="")]
    kept = rule_scope.scope_rules_by_ancestry(rules, "constraint_rules")
    assert len(kept) == 2
    ev = _ev(recs, "ask.rule_scope.filtered")[0]
    assert ev["context"]["rules_total"] == 3 and ev["context"]["rules_in_scope_for_model"] == 2


def test_rule_scope_failure_warns_and_returns_all(recs, monkeypatch):
    from aryx.cpq import rule_scope

    monkeypatch.setattr(rule_scope, "rule_scope_enabled", lambda: True)
    monkeypatch.setattr(rule_scope._model_resolution, "get_turn", MagicMock(side_effect=KeyError("x")))
    rules = [SimpleNamespace(ref_id="10")]
    assert rule_scope.scope_rules_by_ancestry(rules, "recommendation_rules") is rules
    ev = _ev(recs, "ask.rule_scope.failed")[0]
    assert ev["error_code"] == "ARYX_ASK_RULE_SCOPE_FAILED"


def test_resolved_model_prepend_is_not_reported_as_static_fallback(recs, monkeypatch):
    from aryx.cpq.auto_fill_stages import fill_log
    from aryx.cpq.data_table_bridge import candidates as c

    monkeypatch.setattr(c, "dt_resolve_product_cpq_models_from_rows", lambda *a, **k: None)
    monkeypatch.setattr(c, "dt_resolve_product_cpq_model_family", lambda *a, **k: None)
    monkeypatch.setattr(c, "get_settings", lambda: SimpleNamespace(
        data_table_candidates_empty_on_no_match_enabled=False, cpq_model_scope_lookups_enabled=True,
        cpq_candidates_real_models_first_enabled=False))
    monkeypatch.setattr(c._model_resolution, "get_turn", lambda: _bound_turn(set()))
    monkeypatch.setattr(fill_log, "fallback_static_first_in_turn", lambda result: True)
    assert c._cpq_model_candidates("APX 900", 1) == ("APX900", "APXNEXT", "APXNEXT_BOM")
    assert not _ev(recs, "ask.model.fallback_static")
    assert _ev(recs, "ask.model.candidates")[0]["context"]["tier"] == "resolved_model_prepend"


def test_turn_state_logged_once_for_early_exit_turn_and_not_twice_after_step11(monkeypatch):
    from aryx.cpq.auto_fill_stages import fill_log

    out: list[dict] = []
    monkeypatch.setattr(fill_log, "raven_log", lambda lv, cr, msg, **kw: out.append(
        {"message": msg, "context": kw.get("context") or {}}))
    monkeypatch.setattr(fill_log, "would_log", lambda lv: True)
    sd = {"run_id": "run-early", "turn": 2, "filled": {"region": "NA"}, "filled_multi": {},
          "filled_source": {"region": "hint"}, "pending_variables": ["model"]}
    fill_log.turn_state_from_session_data(sd)
    fill_log.turn_state_from_session_data(sd)          # second finish of the same turn: skipped
    states = [r for r in out if r["message"].startswith("ask.turn.state")]
    assert len(states) == 1
    ctx = states[0]["context"]
    assert ctx["object_id"] == "run-early" and ctx["pending_count"] == 1
    assert ctx["values"]["region"] != "NA"             # no attr definitions -> free-text form, never raw
    # a turn step 11 already logged is not logged again from the finish path
    sess = SimpleNamespace(run_id="run-s11", turn=1, filled={}, filled_multi={}, filled_source={},
                           pending_variables=[])
    fill_log.build_turn_state_record(sess, [])
    fill_log.turn_state_from_session_data({"run_id": "run-s11", "turn": 1})
    assert len([r for r in out if r["message"].startswith("ask.turn.state")]) == 2


def test_finish_cpq_result_never_raises_on_bad_session_data():
    from aryx.cpq.auto_fill_stages import fill_log

    fill_log.turn_state_from_session_data("not-a-dict")
    fill_log.turn_state_from_session_data({"filled": object()})
