"""Raven logging for the ingestion pipeline stages + shared DB/LLM layers (area B).

Records are captured from the stdout sink at DEBUG level and asserted on event
name, level, error_code, key context and the content rule (no params/SQL/prompts).
"""
from __future__ import annotations

import json
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

import aryx.raven_log as rl
from aryx.models import ResolutionRecord

SENTINEL = "SENTINEL_BIND_VALUE_9137"


@pytest.fixture(autouse=True)
def _debug_level(monkeypatch):
    monkeypatch.setenv("ARYX_RAVEN_LOG_LEVEL", "DEBUG")
    rl.reload_config()
    rl.bind_run_id("job-42")
    yield
    rl.bind_run_id("")
    monkeypatch.delenv("ARYX_RAVEN_LOG_LEVEL", raising=False)
    rl.reload_config()


def _recs(capsys) -> list[dict]:
    return [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]


def _ev(recs: list[dict], event: str) -> list[dict]:
    return [r for r in recs if r["message"].startswith(event + " ") or r["message"] == event]


# ---------------------------------------------------------------- DB layer

def test_sql_op_is_verb_and_table_only():
    from aryx.store.oracle_cursor import _ora_code, _sql_op
    assert _sql_op("INSERT INTO aryx_entity (a, b) VALUES (:1, :2)") == "INSERT aryx_entity"
    assert _sql_op("select a, b from t where x = :1") == "SELECT t"
    assert _sql_op("MERGE INTO tgt USING dual ON (1=1)") == "MERGE tgt"
    assert _ora_code(Exception("ORA-00942: table or view does not exist")) == "ORA-00942"
    assert _ora_code(Exception("DPY-4011: the database or network closed")) == "DPY-4011"
    assert _ora_code(Exception("boom")) == ""


def test_statement_failure_logs_error_without_params(capsys):
    import time
    from aryx.store.oracle_cursor import _log_stmt_failed, _log_stmt_ok
    _log_stmt_failed("INSERT aryx_entity", "execute", RuntimeError("ORA-01400: cannot insert NULL"), time.monotonic())
    _log_stmt_ok("SELECT t", "execute", 3, time.monotonic())
    recs = _recs(capsys)
    err = _ev(recs, "db.oracle.call_failed")[0]
    assert err["level"] == "ERROR" and err["criticality"] == "P2" and err["error_code"] == "ARYX_DB_CALL_FAILED"
    assert err["trace_id"] == "job-42"
    ctx = err["context"]
    assert ctx["operation"] == "INSERT aryx_entity" and ctx["ora_code"] == "ORA-01400"
    assert ctx["error_class"] == "RuntimeError" and "attempt" in ctx and "duration_ms" in ctx
    assert "params" not in ctx and "row0" not in ctx
    dbg = _ev(recs, "db.oracle.statement")[0]
    assert dbg["level"] == "DEBUG" and dbg["context"]["rows"] == 3


def test_slow_statement_always_logged_at_info(capsys, monkeypatch):
    import time
    monkeypatch.setenv("ARYX_RAVEN_LOG_LEVEL", "INFO")
    rl.reload_config()
    from aryx.store import oracle_cursor as oc
    oc._log_stmt_ok("SELECT t", "execute", 1, time.monotonic() - (oc.SLOW_STATEMENT_MS / 1000 + 1))
    oc._log_stmt_ok("SELECT t", "execute", 1, time.monotonic())
    recs = _recs(capsys)
    assert len(recs) == 1 and recs[0]["message"].startswith("db.oracle.slow_statement")


def test_cursor_execute_failure_end_to_end(capsys):
    import sys
    import types
    fake = types.ModuleType("oracledb")
    fake.IntegrityError = type("IntegrityError", (Exception,), {})
    fake.DB_TYPE_JSON = object()
    with patch.dict(sys.modules, {"oracledb": fake}):
        from aryx.store.oracle_cursor import OracleCursorWrapper
        raw = MagicMock()
        raw.execute.side_effect = RuntimeError("ORA-00942: nope")
        w = OracleCursorWrapper(raw)
        with pytest.raises(RuntimeError):
            w.execute("SELECT a FROM missing_tbl WHERE x = :1", (SENTINEL,))
    out = json.dumps(_recs(capsys))
    assert "db.oracle.call_failed" in out and "missing_tbl" in out
    assert SENTINEL not in out


def test_pool_connection_dropped_warns(capsys):
    from aryx.store.oracle_connection_pool import OraclePool
    pool = OraclePool.__new__(OraclePool)
    pool._pool = MagicMock()
    with pytest.raises(RuntimeError):
        with pool.connection():
            raise RuntimeError("DPY-4011: the database or network closed the connection")
    rec = _ev(_recs(capsys), "db.oracle.connection_dropped")[0]
    assert rec["level"] == "WARN" and rec["criticality"] == "P2" and rec["error_code"] == "ARYX_DB_CONN_DROPPED"
    assert rec["context"]["ora_code"] == "DPY-4011"


# ---------------------------------------------------------------- LLM layer

def test_post_json_429_retries_then_exhausts(capsys):
    from aryx.llm import llm_providers as lp
    err = urllib.error.HTTPError("http://x", 429, "slow", {}, None)
    with patch.object(lp.urllib.request, "urlopen", side_effect=err), patch.object(lp.time, "sleep"):
        with pytest.raises(urllib.error.HTTPError):
            lp.post_json("http://x", {"model": "m1", "messages": [{"content": SENTINEL}]}, {})
    recs = _recs(capsys)
    retries = _ev(recs, "llm.retry.scheduled")
    assert len(retries) == 4
    assert all(r["level"] == "WARN" and r["error_code"] == "ARYX_LLM_RETRY" for r in retries)
    assert retries[0]["context"]["max_attempts"] == 5 and retries[0]["context"]["model"] == "m1"
    ex = _ev(recs, "llm.retry.exhausted")[0]
    assert ex["level"] == "ERROR" and ex["error_code"] == "ARYX_LLM_FAILED" and ex["trace_id"] == "job-42"
    assert SENTINEL not in json.dumps(recs)


def test_post_json_non_retryable_logs_call_failed(capsys):
    from aryx.llm import llm_providers as lp
    err = urllib.error.HTTPError("http://x", 400, "bad", {}, None)
    with patch.object(lp.urllib.request, "urlopen", side_effect=err):
        with pytest.raises(urllib.error.HTTPError):
            lp.post_json("http://x", {"model": "m1"}, {})
    rec = _ev(_recs(capsys), "llm.call.failed")[0]
    assert rec["level"] == "ERROR" and rec["context"]["http_status"] == 400


def test_oci_truncated_json_retry_and_failure(capsys):
    from aryx.broker.specs import ModelSpec
    from aryx.llm import llm_providers_oci as oci
    spec = ModelSpec(name="cohere.x", provider="oci", tier="cheap", endpoint="")
    with patch.object(oci, "_oci_chat_raw", side_effect=[('{"a": "tru', 5, 6), ('{"a": "tru', 7, 8)]):
        with pytest.raises(RuntimeError):
            oci.oci_genai_json(spec, "sys", "user")
    recs = _recs(capsys)
    r = _ev(recs, "llm.retry.scheduled")[0]
    assert r["level"] == "WARN" and r["error_code"] == "ARYX_LLM_RETRY" and r["context"]["tokens_in"] == 5
    assert _ev(recs, "llm.retry.exhausted")[0]["error_code"] == "ARYX_LLM_FAILED"


# ---------------------------------------------------------------- resolve

def _rec(i, text):
    return ResolutionRecord(record_id=i, text=text, payload={"name": text})


def test_route_pair_adjudication_failure_warns_and_counts(capsys):
    from aryx.resolution import run as rr
    from aryx.resolution import stats
    from aryx.resolution.cluster import UnionFind
    cfg = MagicMock(er_auto_merge=0.95, er_adjudicate=0.5, er_review=0.3)
    u = UnionFind()
    u.add(1)
    u.add(2)
    with patch.object(rr, "get_settings", return_value=cfg), \
            patch.object(rr, "adjudicate", side_effect=RuntimeError("llm down")):
        out = rr._route_pair(_rec(1, "a"), _rec(2, "b"), 0.7, MagicMock(), u, None, run_id=7)
    assert out == "adjudicate_no_merge"
    recs = _recs(capsys)
    w = _ev(recs, "ingest.resolve.adjudication_failed")[0]
    assert w["level"] == "WARN" and w["error_code"] == "ARYX_ING_RESOLVE_DEGRADED"
    assert stats.pop(7)["adjudication_failed"] == 1


def test_route_pair_debug_trail_each_band(capsys):
    from aryx.resolution import run as rr
    from aryx.resolution.cluster import UnionFind
    cfg = MagicMock(er_auto_merge=0.9, er_adjudicate=0.8, er_review=0.5)
    for score in (0.95, 0.6, 0.1):
        u = UnionFind()
        u.add(1)
        u.add(2)
        with patch.object(rr, "get_settings", return_value=cfg):
            rr._route_pair(_rec(1, "a"), _rec(2, "b"), score, MagicMock(), u, MagicMock(), run_id=7)
    pairs = _ev(_recs(capsys), "ingest.resolve.pair")
    assert [p["context"]["band"] for p in pairs] == ["auto_merge", "review", "reject"]
    assert pairs[0]["context"]["left_id"] == 1 and pairs[0]["context"]["score"] == 0.95


def test_oversized_block_counted_and_logged(capsys):
    from aryx.resolution import stats
    from aryx.resolution.blocking import MultiKeyBlocker
    recs_in = [_rec(i, "same name") for i in range(5)]
    MultiKeyBlocker(max_block_size=2).block(recs_in, run_id=11)
    recs = _recs(capsys)
    assert _ev(recs, "ingest.resolve.block_skipped")
    assert stats.pop(11)["blocks_skipped_oversized"] >= 1


def test_resolve_run_summary_info_and_degraded(capsys):
    from aryx.resolve_entities import resolve_run
    store = MagicMock()
    store.landed_records.return_value = [_rec(1, "Acme Corp"), _rec(2, "Zed Inc")]
    store.save.return_value = 2
    ws = MagicMock()
    ws.get_survivorship.return_value = {}
    with patch("aryx.resolve_entities.AdjudicationStore", return_value=MagicMock()), \
            patch("aryx.resolve_entities.make_workspace_store", return_value=ws):
        resolve_run(5, "Company", ["name"], store, MagicMock())
    s = _ev(_recs(capsys), "ingest.resolve.summary")[0]
    assert s["level"] in ("INFO", "WARN") and s["context"]["stage"] == "resolve"
    assert s["context"]["impact_scope"]["records"] == 2

    with patch("aryx.resolve_entities.AdjudicationStore", side_effect=RuntimeError("down")), \
            patch("aryx.resolve_entities.make_workspace_store", return_value=ws):
        resolve_run(6, "Company", ["name"], store, MagicMock())
    recs = _recs(capsys)
    s = _ev(recs, "ingest.resolve.summary")[0]
    assert s["level"] == "WARN" and s["error_code"] == "ARYX_ING_RESOLVE_DEGRADED"
    assert s["criticality"] == "P3" and s["context"]["impact_scope"]["review_sink_unavailable"] is True
    assert _ev(recs, "ingest.resolve.path_chosen")


def test_chunked_edge_cap_warns(capsys):
    from aryx.resolution import chunked, stats
    backend = MagicMock()
    backend.edges.return_value = iter([(1, 2, 1.0), (2, 3, 1.0), (3, 4, 1.0)])
    backend.load_records.return_value = []
    with patch.object(chunked, "get_settings", return_value=MagicMock(er_max_edges_per_run=2)), \
            patch.object(chunked, "_materialize", return_value=MagicMock()):
        list(chunked._cluster_pass(9, backend, [1, 2, 3, 4], "T", None))
    w = _ev(_recs(capsys), "ingest.resolve.edge_cap_hit")[0]
    assert w["level"] == "WARN" and w["error_code"] == "ARYX_ING_RESOLVE_DEGRADED"
    assert stats.pop(9)["edge_cap_hit"] == 1


# ---------------------------------------------------------------- relate / fk

def test_fk_abort_is_policy_guard_warn(capsys):
    from aryx.pipeline.fk_edges import link_by_attribute
    est = MagicMock()
    est.conflict_aliases.return_value = {}
    ents = [(1, "T", {"k": "x"})] + [(100 + i, "S", {"c": "x"}) for i in range(5)]
    with patch("aryx.pipeline.fk_edges.get_settings", return_value=MagicMock(max_relationships_per_fk_spec=2)):
        assert link_by_attribute(est, ents, "S", "c", "T", "k", "HAS") == 0
    w = _ev(_recs(capsys), "ingest.fk.aborted")[0]
    c = w["context"]
    assert w["level"] == "WARN" and w["error_code"] == "ARYX_ING_FK_ABORTED"
    assert c["decision"] == "deny" and c["reason_code"] == "NOT_SELECTIVE" and c["policy_version"] == 2
    assert c["resource"] == "S.c->T.k" and c["requested_action"] == "link_fk"


def test_relate_partial_failure_summary_warns(capsys):
    from aryx.pipeline.enrich import enrich_relate as er
    store = MagicMock()
    store.list_entities_typed_sample.return_value = [(1, "A", {"x": 1}), (2, "B", {"y": 2})]
    cfg = MagicMock(relate_workers=2, relate_max_attrs=5, relate_pair_timeout=5)
    with patch.object(er, "get_settings", return_value=cfg), \
            patch.object(er, "infer_relationship", side_effect=RuntimeError("bad")):
        er._relate(store, MagicMock(), 3)
    recs = _recs(capsys)
    w = _ev(recs, "ingest.relate.summary")[0]
    assert w["level"] == "WARN" and w["error_code"] == "ARYX_ING_RELATE_DEGRADED"
    assert w["context"]["pairs_failed"] == 1 and w["context"]["pairs_total"] == 1
    assert w["trace_id"] == "job-42"  # submit_ctx carried the bound id through; summary is main thread


def test_submit_ctx_worker_carries_trace_id(capsys):
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool_fut = rl.submit_ctx(pool, lambda: rl.raven_log("INFO", "P4", "x.y worker"))
        pool_fut.result()
    assert _recs(capsys)[0]["trace_id"] == "job-42"


# ---------------------------------------------------------------- project

def test_project_auto_mode_decisions(capsys):
    from aryx.project import project_auto
    pstore = MagicMock()
    pstore.watermark.return_value = None
    graph = MagicMock()
    with patch("aryx.project.project_graph", return_value={"entities": 1}):
        project_auto(MagicMock(), pstore, graph, workspace_id=3)
    full = _ev(_recs(capsys), "ingest.project.mode_chosen")[0]
    assert full["context"]["selected_option"] == "full" and full["context"]["reason_code"] == "NO_WATERMARK"

    pstore.watermark.return_value = "wm"
    pstore.total_entities.return_value = 100
    pstore.dirty_entities.return_value = [1, 2]
    with patch("aryx.project.project_incremental", return_value={"entities": 2}):
        project_auto(MagicMock(), pstore, graph, workspace_id=3)
    inc = _ev(_recs(capsys), "ingest.project.mode_chosen")[0]
    assert inc["context"]["selected_option"] == "incremental"


def test_project_workspace_graph_failure_is_p1_and_reraises(capsys):
    from aryx.pipeline import orchestrate as orch
    from aryx.resolution.stats import bump
    cfg = MagicMock()
    cfg.effective_graph_backend.return_value = "falkordb"

    def _boom(*a, **k):
        bump(("project", 4), "cleared")
        raise RuntimeError("graph write failed")

    with patch.object(orch, "get_settings", return_value=cfg), \
            patch.object(orch, "_build_type_ancestors", return_value={}), \
            patch.object(orch, "FalkorStore", return_value=MagicMock()), \
            patch.object(orch, "ProjectionStore", return_value=MagicMock()), \
            patch.object(orch, "project_auto", side_effect=_boom):
        with pytest.raises(RuntimeError, match="graph write failed"):
            orch.project_workspace_graph("dsn", "url", 4, MagicMock())
    rec = _ev(_recs(capsys), "ingest.project.failed")[0]
    assert rec["level"] == "ERROR" and rec["criticality"] == "P1" and rec["error_code"] == "ARYX_ING_PROJECT_FAILED"
    assert rec["context"]["cleared_before_failure"] is True and rec["context"]["stage"] == "project"


def test_project_workspace_graph_success_logs_completed(capsys):
    from aryx.pipeline import orchestrate as orch
    cfg = MagicMock()
    cfg.effective_graph_backend.return_value = "falkordb"
    with patch.object(orch, "get_settings", return_value=cfg), \
            patch.object(orch, "_build_type_ancestors", return_value={}), \
            patch.object(orch, "FalkorStore", return_value=MagicMock()), \
            patch.object(orch, "ProjectionStore", return_value=MagicMock()), \
            patch.object(orch, "project_auto", return_value={"entities": 3}):
        assert orch.project_workspace_graph("dsn", "url", 4, MagicMock()) == {"entities": 3}
    rec = _ev(_recs(capsys), "ingest.project.completed")[0]
    assert rec["level"] == "INFO" and rec["context"]["mode"] == "full" and rec["context"]["counts"] == {"entities": 3}


# ---------------------------------------------------------------- stages

def test_stage_runner_skip_start_finish_failed(capsys):
    from aryx.pipeline import stages
    with patch.object(stages, "StageTracker") as tr:
        tr.return_value.statuses.return_value = {"resolve_cluster": "done", "relate": "running"}
        runner = stages.StageRunner("dsn", 9, resume=True)
        assert runner.skip("resolve_cluster") and not runner.skip("relate")
        with runner.stage("relate"):
            pass
        with pytest.raises(ValueError):
            with runner.stage("project"):
                raise ValueError("x")
    recs = _recs(capsys)
    assert _ev(recs, "ingest.stage.resume")[0]["context"]["stages_done"] == ["resolve_cluster"]
    assert _ev(recs, "ingest.stage.skipped")
    assert _ev(recs, "ingest.stage.started") and _ev(recs, "ingest.stage.finished")
    f = _ev(recs, "ingest.stage.failed")[0]
    assert f["level"] == "ERROR" and f["error_code"] == "ARYX_ING_STAGE_FAILED"


def test_check_cancelled_logs_both_sides(capsys):
    from aryx.pipeline.orchestrate import PipelineCancelled, _check_cancelled
    _check_cancelled(lambda: False, "relate")
    with pytest.raises(PipelineCancelled):
        _check_cancelled(lambda: True, "project")
    recs = _recs(capsys)
    assert _ev(recs, "ingest.pipeline.cancel_check")[0]["level"] == "DEBUG"
    assert _ev(recs, "ingest.pipeline.cancelled")[0]["error_code"] == "ARYX_ING_CANCELLED"


def test_discover_logs_tagging_off_and_spine(capsys):
    from aryx import discover as d
    store = MagicMock()
    store.start_run.return_value = 77
    sink = MagicMock(total=0)
    with patch.object(d, "BatchSink", return_value=sink), patch.object(d, "run_spine", return_value=[]):
        assert d.discover(MagicMock(), store, "sys", "ds") == 77
    recs = _recs(capsys)
    assert _ev(recs, "ingest.discover.tagging")[0]["context"]["selected_option"] == "skip_tag"
    assert _ev(recs, "ingest.discover.landed")


def test_no_forbidden_content_in_dynamic_fk_verdict(capsys):
    from aryx.pipeline.dynamic_fk import dynamic_fk as dfk
    cand = {"type_a": "A", "col_a": "x", "type_b": "B", "col_b": "y", "overlap": 0.9,
            "samples_a": [SENTINEL], "samples_b": [SENTINEL], "transform": None}
    with patch.object(dfk, "complete_json", return_value={"verdicts": [
            {"index": 0, "linked": True, "reason": SENTINEL}]}):
        links = dfk._judge_batch([cand], MagicMock(), "lid")
    assert links[0] is not None
    out = json.dumps(_recs(capsys))
    assert "ingest.fk.verdict" in out and SENTINEL not in out
