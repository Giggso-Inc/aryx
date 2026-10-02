"""Raven structured-log placements for ingestion intake and the job lifecycle (area A).

Each test triggers one branch and captures the records by replacing the
module-level ``raven_log`` / ``would_log`` names in the module under test.
No database is used: stores are faked the way the existing ingest tests do.
"""
from __future__ import annotations

import importlib
import json
import threading
from unittest.mock import MagicMock, patch

import pytest

from aryx.raven_log import bind_run_id, current_run_id
from aryx.worker.job_partial import note_hidden, pop_hidden

SENTINEL = "SENTINEL_ROW_VALUE_9137"
_MODULES = [
    "aryx.api.file_ingest.file_ingest_api", "aryx.api.file_ingest.file_ingest_run",
    "aryx.api.rest_ingest.rest_ingest_job", "aryx.api.connect_api", "aryx.api.admin_api",
    "aryx.api.jobs_api", "aryx.api.main_lifespan", "aryx.api.doc_discover.doc_discover_api",
    "aryx.api.doc_discover.doc_discover_read_job", "aryx.api.doc_discover.doc_discover_confirm_job",
    "aryx.worker.oci_functions_worker", "aryx.worker.oci_dataflow_worker", "aryx.worker.fn_handler",
    "aryx.worker.fn_handler_dispatch", "aryx.store.job_store", "aryx.store.datasource_store_crud",
    "aryx.cpq_ingestion.csv_land", "aryx.cpq_ingestion.layout_store", "aryx.cpq_ingestion.pipeline",
    "aryx.cpq_ingestion.routing", "aryx.cpq_ingestion.raw_graph.store",
    "aryx.cpq_ingestion.raw_graph.match_key_inference", "aryx.connectors.csv_source",
    "aryx.connectors.rest_api", "aryx.connectors.doc_router", "aryx.connectors.doc_router_ingest",
    "aryx.connectors.doc_router_select", "aryx.ontology.extract",
    "aryx.pipeline.doc_discovery.doc_discovery", "aryx.pipeline.doc_discovery.doc_discovery_xml",
    "aryx.pipeline.doc_discovery.doc_discovery_xlsx", "aryx.pipeline.doc_discovery.doc_discovery_types",
]


@pytest.fixture()
def records(monkeypatch):
    """Capture every raven_log call made through any area-A module."""
    out: list[dict] = []

    def fake(level, criticality, message, *, error_code="", context=None, trace_id=None, **kw):
        out.append({"level": level, "crit": criticality, "message": message, "error_code": error_code,
                    "context": context or {}, "trace_id": trace_id or current_run_id()})
        return {}

    for name in _MODULES:
        mod = importlib.import_module(name)
        if hasattr(mod, "raven_log"):
            monkeypatch.setattr(mod, "raven_log", fake)
        if hasattr(mod, "would_log"):
            monkeypatch.setattr(mod, "would_log", lambda level: True)
    bind_run_id("job-test")
    pop_hidden("job-test")
    yield out
    bind_run_id("")


def _events(recs, name):
    return [r for r in recs if r["message"].startswith(name)]


def _assert_clean(recs):
    blob = json.dumps(recs, default=str)
    assert SENTINEL not in blob


def test_csv_direct_landing_logs_start_and_rows(records):
    from aryx.cpq_ingestion import csv_land
    store = MagicMock()
    store.count_landed.return_value = 2
    ds = MagicMock()
    with patch.object(csv_land, "PostgresStore", return_value=store), \
            patch.object(csv_land, "discover", return_value=7), \
            patch.object(csv_land, "DatasourceStore", return_value=ds):
        csv_land.land_csv_directly(f"id,name\n1,{SENTINEL}\n".encode(), "stem", workspace_id=1, dsn="d", log_id="job-test")
    assert _events(records, "ingest.csv_direct.start")[0]["level"] == "INFO"
    landed = _events(records, "ingest.csv_direct.landed")[0]
    assert landed["context"]["rows_landed"] == 2 and landed["trace_id"] == "job-test"
    _assert_clean(records)


def test_csv_direct_datasource_failure_is_warn_and_marks_job_partial(records):
    from aryx.cpq_ingestion import csv_land
    store = MagicMock()
    store.count_landed.return_value = 1
    ds = MagicMock()
    ds.ensure.side_effect = RuntimeError("adb down")
    with patch.object(csv_land, "PostgresStore", return_value=store), \
            patch.object(csv_land, "discover", return_value=1), \
            patch.object(csv_land, "DatasourceStore", return_value=ds):
        csv_land.land_csv_directly(b"id\n1\n", "s", workspace_id=1, dsn="d")
    ev = _events(records, "ingest.datasource.register_failed")[0]
    assert ev["level"] == "WARN" and ev["error_code"] == "ARYX_ING_DATASOURCE_FAILED"
    assert ev["context"]["error_class"] == "RuntimeError"
    assert pop_hidden("job-test") == 1


def test_layout_too_large_warns_and_raises(records):
    from aryx.cpq_ingestion import layout_store
    big = b"x" * (layout_store._MAX_LAYOUT_FILE_BYTES + 1)
    with pytest.raises(layout_store.CpqLayoutFileTooLarge):
        layout_store.store_layout_file(big, "f.txt", workspace_id=1, dsn="d")
    ev = _events(records, "ingest.layout.too_large")[0]
    assert ev["level"] == "WARN" and ev["error_code"] == "ARYX_ING_LAYOUT_SKIPPED"
    assert ev["context"]["measured"] == len(big)


def test_raw_graph_failure_continues_csv_ingest(records, monkeypatch):
    from aryx.cpq_ingestion import pipeline
    monkeypatch.setattr(pipeline, "get_cpq_ingestion_settings", lambda: MagicMock(cpq_raw_graph_enabled=True))
    monkeypatch.setattr(pipeline, "project_and_write_raw_graph", MagicMock(side_effect=ValueError("boom")))
    monkeypatch.setattr(pipeline, "_xml_to_csvs", lambda d, s, log_id=None: [(b"a", "s.csv")])
    out = pipeline.project_raw_graph_and_flatten(b"<a/>", "s", workspace_id=1, dsn="d", graph_url="g")
    assert out == [(b"a", "s.csv")]
    ev = _events(records, "ingest.raw_graph.write_failed")[0]
    assert ev["level"] == "WARN" and ev["error_code"] == "ARYX_ING_RAW_GRAPH_FAILED"
    assert ev["context"]["recovery_selected"] == "continue_csv_ingest"
    assert pop_hidden("job-test") == 1


def test_xml_fallbacks_log_reason_codes(records):
    from aryx.pipeline.doc_discovery.doc_discovery_xml import _xml_to_csvs
    _xml_to_csvs(b"<not xml", "s")
    _xml_to_csvs(b"<a><b>1</b></a>", "s")
    reasons = [r["context"]["reason_code"] for r in _events(records, "ingest.xml.fallback_raw")]
    assert reasons == ["PARSE_FAILED", "NO_ENTITIES"]
    assert all(r["error_code"] == "ARYX_ING_XML_FALLBACK" for r in _events(records, "ingest.xml.fallback_raw"))


def test_rest_page_failure_logs_host_only(records):
    from aryx.connectors import rest_api
    calls = {"n": 0}

    def req(url, headers, timeout=30):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"items": [{"id": 1}], "next": "tok"}
        raise OSError("net down")

    conn = rest_api.RestApiConnector("https://api.example.com/v1/x?secret=abc", {"Authorization": "Bearer t0k"},
                                     record_path="items", page_param="p", next_page_path="next", max_pages=5)
    with patch.object(rest_api, "_request", req):
        got = list(conn.extract())
    assert len(got) == 1
    ev = _events(records, "ingest.rest.page_failed")[0]
    assert ev["level"] == "WARN" and ev["error_code"] == "ARYX_ING_REST_PARTIAL"
    assert ev["context"]["url_host"] == "api.example.com" and ev["context"]["records_kept"] == 1
    blob = json.dumps(records)
    assert "secret=abc" not in blob and "t0k" not in blob


def test_extract_mentions_all_failed_is_error_and_trace_crosses_pool(records, monkeypatch):
    from aryx.models import DocumentChunk, SourceRef
    from aryx.ontology.extract import extract_mentions
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_RETRIES", "1")
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_RETRY_DELAY", "0")
    from aryx.config import get_settings
    get_settings.cache_clear()
    seen = []

    def fail(*a, **k):
        seen.append(current_run_id())
        raise ValueError("bad json")

    chunk = DocumentChunk(doc_id="d" * 64, chunk_index=0, text=SENTINEL,
                          source=SourceRef(system="document", dataset="u", record_id="x"))
    with patch("aryx.ontology.extract.complete_json", side_effect=fail):
        assert extract_mentions([chunk], broker=MagicMock()) == []
    ev = _events(records, "ingest.mentions.all_failed")[0]
    assert ev["level"] == "ERROR" and ev["error_code"] == "ARYX_ING_LLM_EXTRACT_FAILED"
    assert ev["context"]["error_class"] == "ValueError"
    assert seen == ["job-test"], "pool worker must see the submitting thread's bound id"
    _assert_clean(records)


def test_sweep_stale_logs_only_when_count_positive(records):
    from aryx.store import job_store
    pool = MagicMock()
    cur = pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    store = job_store.JobStore.__new__(job_store.JobStore)
    store._pool = pool
    cur.rowcount = 0
    with patch.object(job_store, "load", lambda n: n):
        store.sweep_stale(120)
        assert not _events(records, "ingest.job.swept_stale")
        cur.rowcount = 3
        store.sweep_stale(120)
    ev = _events(records, "ingest.job.swept_stale")[0]
    assert ev["level"] == "WARN" and ev["error_code"] == "ARYX_ING_JOB_STALE" and ev["context"]["count"] == 3


def test_dispatch_failure_logs_then_reraises(records):
    from aryx.worker import oci_functions_worker as w
    fake_oci = MagicMock()
    fake_oci.functions.FunctionsInvokeClient.return_value.invoke_function.side_effect = RuntimeError("401")
    fake_client = MagicMock()
    fake_client._get_auth.return_value = {}
    with patch.dict("sys.modules", {"oci": fake_oci, "aryx.oci_client": fake_client}):
        with pytest.raises(RuntimeError):
            w.submit_to_oci_function("ocid", {"job_id": "job-test", "file_b64": SENTINEL})
    ev = _events(records, "ingest.dispatch.failed")[0]
    assert ev["level"] == "ERROR" and ev["error_code"] == "ARYX_ING_DISPATCH_FAILED"
    assert ev["context"]["dependency_name"] == "oci_functions" and ev["context"]["job_id"] == "job-test"
    _assert_clean(records)


def test_run_files_completed_and_partial(records, monkeypatch):
    from aryx.api.file_ingest import file_ingest_run as run
    jobs = MagicMock()
    monkeypatch.setattr(run, "JobStore", lambda dsn: jobs)
    monkeypatch.setattr(run, "DatasourceStore", lambda dsn: MagicMock())
    monkeypatch.setattr(run, "get_settings", lambda: MagicMock(effective_dsn=lambda: "d", csv_chunk_rows=0,
                                                                ingest_relate=False))
    monkeypatch.setattr(run, "_local_broker", lambda: MagicMock())
    monkeypatch.setattr(run, "run_pipeline", MagicMock())
    monkeypatch.setattr(run, "restore_generic_source_entry", MagicMock())
    bind_run_id("")
    run._run_files([], "T", ["id"], [], "job-ok", 1)
    ok = _events(records, "ingest.job.completed")[0]
    assert ok["context"]["result"] == "ok" and ok["trace_id"] == "job-ok"
    # a hidden failure fired during the job flips the result to partial
    def layout_active(name):
        note_hidden("job-part")
        return False

    monkeypatch.setattr(run, "cpq_layout_upload_active", layout_active)
    run._run_files([(b"x", "a.csv")], "T", ["id"], [], "job-part", 1)
    part = _events(records, "ingest.job.completed")[1]
    assert part["context"]["result"] == "partial" and part["context"]["reason_code"] == "HIDDEN_FAILURES"


def test_run_files_failure_logs_stage_and_error_class(records, monkeypatch):
    from aryx.api.file_ingest import file_ingest_run as run
    jobs = MagicMock()
    monkeypatch.setattr(run, "JobStore", lambda dsn: jobs)
    monkeypatch.setattr(run, "DatasourceStore", lambda dsn: MagicMock())
    monkeypatch.setattr(run, "get_settings", lambda: MagicMock(effective_dsn=lambda: "d"))
    monkeypatch.setattr(run, "_local_broker", lambda: MagicMock())
    monkeypatch.setattr(run, "cpq_layout_upload_active", MagicMock(side_effect=KeyError("k")))
    run._run_files([(b"x", "a.csv")], "T", ["id"], [], "job-bad", 1)
    ev = _events(records, "ingest.job.failed")[0]
    assert ev["level"] == "ERROR" and ev["error_code"] == "ARYX_ING_JOB_FAILED"
    assert ev["context"]["error_class"] == "KeyError" and ev["context"]["stage"] == "start"
    assert ev["trace_id"] == "job-bad"
    jobs.finish.assert_called_with("job-bad", run_id=None, status="failed", error="'k'")


def test_csv_read_logs_header_names_not_values(records):
    from aryx.connectors.csv_source import CsvConnector
    rows = list(CsvConnector(f"alpha,beta\n{SENTINEL},2\n".encode(), dataset="d").extract())
    assert len(rows) == 1
    read = _events(records, "ingest.csv.read source decoded")[0]
    assert read["context"]["header_columns"] == ["alpha", "beta"]
    assert _events(records, "ingest.csv.read finished")[0]["context"]["records"] == 1
    _assert_clean(records)


def test_infer_type_logs_source_filename_vs_llm(records):
    from aryx.pipeline.doc_discovery import doc_discovery_types as t
    with patch.object(t.llm_runtime, "chat", return_value=('{"ontology_type":"X","match_keys":["id"]}', None)):
        t._infer_type("id,name\n1,a", "customers.csv", "")
        t._infer_type("id,name\n1,a", "data.csv", "")
    decided = _events(records, "ingest.infer.type decided")
    assert [d["context"]["type_source"] for d in decided] == ["filename", "llm"]


def test_job_partial_counter_is_per_job():
    note_hidden("a")
    note_hidden("a")
    assert pop_hidden("a") == 2 and pop_hidden("a") == 0 and pop_hidden("b") == 0


def test_bound_id_is_thread_local_via_submit_ctx():
    from concurrent.futures import ThreadPoolExecutor
    from aryx.raven_log import submit_ctx
    bind_run_id("job-ctx")
    with ThreadPoolExecutor(1) as pool:
        assert submit_ctx(pool, current_run_id).result() == "job-ctx"
    holder = []
    t = threading.Thread(target=lambda: holder.append(current_run_id()))
    t.start(); t.join()
    assert holder == [""]
    bind_run_id("")
