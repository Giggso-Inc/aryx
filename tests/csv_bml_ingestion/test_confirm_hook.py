"""BML CSV pipeline from the Documents flow: which plans it takes, best-effort behaviour, and the ingest_confirmed wiring."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aryx.csv_bml_ingestion import confirm_hook as ch
from aryx.csv_bml_ingestion.options import IngestResult
from aryx.pipeline.doc_discovery.doc_discovery import ingest_confirmed

BODY = b"id,name\n1,Widget\n"


def _plan(filename, **extra):
    return {"filename": filename, "ontology_type": "T", "match_keys": ["id"], "data": BODY, **extra}


# --- which plans are taken -----------------------------------------------------------------------------
def test_only_plain_csv_uploads_are_taken():
    plans = [_plan("whitelist.csv"), _plan("UPPER.CSV"),
             _plan("derived.csv", source_filename="order.xml"),            # fanned out of an XML/XLSX parent
             _plan("APX_next.summary.csv", source_filename="APX_next.xml", cpq_raw_graph_preview=True),   # XML preview plan
             _plan("layout.csv", kind="cpq_layout"),
             _plan("notes.json"), _plan("noext")]
    assert [p["filename"] for p in ch.bml_csv_plans(plans)] == ["whitelist.csv", "UPPER.CSV"]


# --- running them ---------------------------------------------------------------------------------------
class FakeSession:
    instances: list = []

    def __init__(self, workspace_id, job_id=None):
        self.workspace_id, self.job_id, self.calls = workspace_id, job_id, []
        FakeSession.instances.append(self)

    def ingest(self, data, filename):
        self.calls.append((data, filename))
        return RESULTS[filename]


RESULTS = {
    "good.csv": IngestResult(source="good.csv", status="loaded", table="good", physical_table="ws7_good", rows_loaded=2),
    "nomatch.csv": IngestResult(source="nomatch.csv", status="skipped", table="nomatch", error_code="CBI_BML_NOT_FOUND"),
    "broken.csv": IngestResult(source="broken.csv", status="failed", table="broken", error_code="CBI_SCHEMA_MISMATCH"),
}


@pytest.fixture
def hook(monkeypatch):
    FakeSession.instances = []
    seen = {"hidden": [], "raven": []}
    monkeypatch.setattr(ch, "CsvBmlUploadSession", FakeSession)
    monkeypatch.setattr(ch, "note_hidden", lambda job_id=None: seen["hidden"].append(job_id))
    monkeypatch.setattr(ch, "raven_log", lambda level, crit, msg, **kw: seen["raven"].append((level, crit, msg, kw)))
    return seen


def test_each_plain_csv_goes_through_the_session_with_its_bytes_and_name(hook):
    stages = []
    out = ch.ingest_csv_plans_with_bml([_plan("good.csv"), _plan("derived.csv", source_filename="x.xml")],
                                       workspace_id=7, job_id="job-1", on_stage=stages.append)
    (session,) = FakeSession.instances
    assert (session.workspace_id, session.job_id, session.calls) == (7, "job-1", [(BODY, "good.csv")])
    assert [r.status for r in out] == ["loaded"] and stages == ["Processing good.csv (csv_bml_ingestion)"]


def test_a_loaded_file_is_an_info_record_and_a_skip_or_failure_is_a_warning_and_a_hidden_problem(hook):
    ch.ingest_csv_plans_with_bml([_plan("good.csv"), _plan("nomatch.csv"), _plan("broken.csv")],
                                 workspace_id=7, job_id="job-1")
    levels = [(lvl, kw.get("error_code", "")) for lvl, _c, _m, kw in hook["raven"]]
    assert levels == [("INFO", ""), ("WARN", "CBI_BML_NOT_FOUND"), ("WARN", "CBI_SCHEMA_MISMATCH")]
    assert hook["hidden"] == ["job-1", "job-1"]                                  # only the two that did not load
    info = hook["raven"][0][3]["context"]
    assert (info["table"], info["rows_loaded"], info["workspace_id"], info["job_id"]) == ("ws7_good", 2, 7, "job-1")


def test_nothing_in_the_hook_can_raise(monkeypatch, hook):
    class Boom(FakeSession):
        def ingest(self, data, filename):
            raise RuntimeError("boom")
    monkeypatch.setattr(ch, "CsvBmlUploadSession", Boom)
    out = ch.ingest_csv_plans_with_bml([_plan("good.csv")], workspace_id=7, job_id="j",
                                       on_stage=lambda d: (_ for _ in ()).throw(RuntimeError("progress failed")))
    assert [(r.status, r.error_code) for r in out] == [("failed", "CBI_UNEXPECTED")]

    def no_session(*a, **k):
        raise RuntimeError("no database")
    monkeypatch.setattr(ch, "CsvBmlUploadSession", no_session)
    assert ch.ingest_csv_plans_with_bml([_plan("good.csv")], workspace_id=7, job_id="j") == []


# --- wiring inside ingest_confirmed (same harness as the CSV direct-landing tests) ------------------------------
def _confirm(monkeypatch, *, flag, tabular, approved):
    if flag:
        monkeypatch.setenv("ARYX_CSV_BML_ENABLED", "true")
    else:
        monkeypatch.delenv("ARYX_CSV_BML_ENABLED", raising=False)
    jobs = MagicMock()
    base = "aryx.pipeline.doc_discovery.doc_discovery."
    with patch(base + "get_settings") as gs, patch(base + "DatasourceStore", return_value=MagicMock()), \
         patch(base + "run_pipeline"), patch(base + "OntologyStore", return_value=MagicMock()), \
         patch(base + "_detect_fk_links", return_value=[]), patch(base + "_detect_script_data_flow_links", return_value=[]), \
         patch(base + "_detect_fk_links_workspace", return_value=[]), patch(base + "_persist_tabular_sources"), \
         patch(base + "restore_generic_source_entry"), patch(base + "detect_dynamic_fk_links", return_value=[]), \
         patch("aryx.cpq_ingestion.csv_land.land_csv_directly",
               return_value={"run_id": 1, "source_key": "x", "rows_landed": 1}) as land, \
         patch("aryx.csv_bml_ingestion.confirm_hook.ingest_csv_plans_with_bml") as bml:
        s = MagicMock()
        s.effective_dsn.return_value, s.graph_url, s.ingest_workers, s.ingest_relate = "dsn", "url", 1, True
        gs.return_value = s
        ingest_confirmed({"mentions": [], "tabular": tabular}, [], approved, broker=MagicMock(), jobs=jobs,
                         job_id="job-docs", workspace_id=879)
    return bml, land, jobs


def test_the_confirm_step_sends_approved_csvs_to_the_bml_pipeline_when_enabled(monkeypatch):
    bml, land, jobs = _confirm(monkeypatch, flag=True, tabular=[_plan("whitelist.csv", cpq_csv_direct=True)],
                               approved=["whitelist.csv"])
    bml.assert_called_once()
    plans = bml.call_args.args[0]
    assert [p["filename"] for p in plans] == ["whitelist.csv"]
    assert (bml.call_args.kwargs["workspace_id"], bml.call_args.kwargs["job_id"]) == (879, "job-docs")
    assert callable(bml.call_args.kwargs["should_stop"])                         # the job's cancellation check is passed in
    land.assert_called_once()                                                    # additive: the existing landing still runs
    bml.call_args.kwargs["on_stage"]("Processing whitelist.csv (csv_bml_ingestion)")
    assert jobs.update_stage.call_args.args[:2] == ("job-docs", "CSV BML Ingestion")


def test_the_confirm_step_does_not_touch_the_bml_pipeline_when_the_switch_is_off(monkeypatch):
    bml, land, _ = _confirm(monkeypatch, flag=False, tabular=[_plan("whitelist.csv", cpq_csv_direct=True)],
                            approved=["whitelist.csv"])
    bml.assert_not_called()
    land.assert_called_once()                                                    # behaviour unchanged


def test_cancelling_the_job_stops_the_remaining_files(hook):
    asked = []

    def stop_after_one():
        asked.append(1)
        return len(asked) > 1                                                    # ok for the first file, stop for the second
    out = ch.ingest_csv_plans_with_bml([_plan("good.csv"), _plan("nomatch.csv")], workspace_id=7, job_id="j",
                                       should_stop=stop_after_one)
    assert [r.source for r in out] == ["good.csv"] and FakeSession.instances[0].calls == [(BODY, "good.csv")]
    cancelled = [kw for lvl, _c, _m, kw in hook["raven"] if kw.get("error_code") == "ARYX_ING_CANCELLED"]
    assert len(cancelled) == 1 and cancelled[0]["context"]["files_skipped"] == ["nomatch.csv"]   # not silent: the skipped file is named
    assert hook["hidden"] == ["j"]                                               # and the job gets one hidden problem
    out = ch.ingest_csv_plans_with_bml([_plan("good.csv")], workspace_id=7, job_id="j",
                                       should_stop=lambda: (_ for _ in ()).throw(RuntimeError("cancel check failed")))
    assert [r.status for r in out] == ["loaded"]                                 # a broken cancel check never blocks a load


def test_in_a_mixed_batch_the_xml_is_confirmed_before_the_csvs_are_looked_up(monkeypatch):
    """XML + CSV approved together: the CSV is searched in the curated graph, so the XML's Confirm must come first."""
    monkeypatch.setenv("ARYX_CSV_BML_ENABLED", "true")
    order = []
    xml_plan = {"filename": "po_Order.csv", "ontology_type": "Order", "match_keys": ["_text"], "data": b"Id\nPO-1\n",
                "source_filename": "po.xml", "source_bytes": b"<PurchaseOrder Id='PO-1'/>"}
    base = "aryx.pipeline.doc_discovery.doc_discovery."
    with patch(base + "get_settings") as gs, patch(base + "DatasourceStore", return_value=MagicMock()), \
         patch(base + "run_pipeline"), patch(base + "OntologyStore", return_value=MagicMock()), \
         patch(base + "_detect_fk_links", return_value=[]), patch(base + "_detect_script_data_flow_links", return_value=[]), \
         patch(base + "_detect_fk_links_workspace", return_value=[]), patch(base + "_persist_tabular_sources"), \
         patch(base + "restore_generic_source_entry"), patch(base + "detect_dynamic_fk_links", return_value=[]), \
         patch("aryx.cpq_ingestion.routing.cpq_ingestion_pipeline_active", side_effect=lambda fn: fn == "po.xml"), \
         patch("aryx.cpq_ingestion.csv_land.land_csv_directly", return_value={"run_id": 1, "source_key": "x", "rows_landed": 1}), \
         patch("aryx.cpq_ingestion.raw_graph.xml_projector.project_xml_to_raw_graph", return_value="PROJECTION"), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.resolve_and_relate_raw_graph",
               side_effect=lambda *a, **k: (order.append("xml"), {"tags": 1, "entities": 1, "relationships": 0})[1]), \
         patch("aryx.csv_bml_ingestion.confirm_hook.ingest_csv_plans_with_bml",
               side_effect=lambda plans, **k: order.append(("csv", [p["filename"] for p in plans]))):
        s = MagicMock()
        s.effective_dsn.return_value, s.graph_url, s.ingest_workers, s.ingest_relate = "dsn", "url", 1, True
        gs.return_value = s
        ingest_confirmed({"mentions": [], "tabular": [xml_plan, _plan("whitelist.csv", cpq_csv_direct=True)]}, [],
                         ["po_Order.csv", "whitelist.csv"], broker=MagicMock(), jobs=MagicMock(), job_id="job-mixed",
                         workspace_id=879)
    assert order == ["xml", ("csv", ["whitelist.csv"])]                          # the XML plan itself is never sent to BML
