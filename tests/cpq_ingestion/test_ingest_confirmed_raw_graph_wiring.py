"""ingest_confirmed()'s cpq_ingestion wiring: an XML source file whose plans
are cpq_ingestion-active gets resolved/related once per FILE (not once per
per-tag CSV plan) via resolve_and_relate_raw_graph(), and is excluded from
the generic CSV pipeline (FK detection + _run_one_plan/run_pipeline) so the
same records are never resolved twice.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aryx.pipeline.doc_discovery.doc_discovery import ingest_confirmed
from aryx.pipeline.orchestrate import PipelineCancelled

XML_BYTES = b"<PurchaseOrder Id='PO-1'><Customer Id='C-1'/></PurchaseOrder>"


def _xml_plan(filename: str, otype: str, source_filename: str) -> dict:
    return {
        "filename": filename, "ontology_type": otype, "match_keys": ["_text"],
        "data": b"Id\nPO-1\n", "source_filename": source_filename, "source_bytes": XML_BYTES,
    }


def _csv_plan(filename: str, otype: str) -> dict:
    return {
        "filename": filename, "ontology_type": otype, "match_keys": ["id"],
        "data": b"id,name\n1,Widget\n",
    }


def _run(*, tabular, approved_files, cpq_active_for=frozenset(), job_id="job-cpq-wiring",
         jobs=None, resolve_and_relate_result=None):
    data = {"mentions": [], "tabular": tabular}
    jobs = jobs if jobs is not None else MagicMock()
    with patch("aryx.pipeline.doc_discovery.doc_discovery.get_settings") as mock_settings, \
         patch("aryx.pipeline.doc_discovery.doc_discovery.DatasourceStore", return_value=MagicMock()), \
         patch("aryx.pipeline.doc_discovery.doc_discovery.run_pipeline") as mock_run_pipeline, \
         patch("aryx.pipeline.doc_discovery.doc_discovery.OntologyStore", return_value=MagicMock()), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._detect_fk_links", return_value=[]) as mock_fk, \
         patch("aryx.pipeline.doc_discovery.doc_discovery._detect_script_data_flow_links", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._detect_fk_links_workspace", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._persist_tabular_sources") as mock_persist, \
         patch("aryx.pipeline.doc_discovery.doc_discovery.restore_generic_source_entry"), \
         patch("aryx.pipeline.doc_discovery.doc_discovery.detect_dynamic_fk_links", return_value=[]), \
         patch("aryx.cpq_ingestion.routing.cpq_ingestion_pipeline_active",
               side_effect=lambda fn: fn in cpq_active_for) as mock_active, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.resolve_and_relate_raw_graph",
               return_value=resolve_and_relate_result or {"tags": 2, "entities": 2, "relationships": 1},
               ) as mock_bridge, \
         patch("aryx.cpq_ingestion.raw_graph.xml_projector.project_xml_to_raw_graph",
               return_value="PROJECTION") as mock_project:
        settings_mock = MagicMock()
        settings_mock.effective_dsn.return_value = "postgresql://x"
        settings_mock.graph_url = "redis://x"
        settings_mock.ingest_workers = 1
        settings_mock.ingest_relate = True
        mock_settings.return_value = settings_mock
        ingest_confirmed(
            data, [], approved_files, broker=MagicMock(),
            jobs=jobs, job_id=job_id, workspace_id=879,
        )
    return {
        "jobs": jobs, "run_pipeline": mock_run_pipeline, "fk": mock_fk,
        "persist": mock_persist, "active": mock_active, "bridge": mock_bridge,
        "project": mock_project, "settings": settings_mock,
    }


def test_cpq_active_xml_file_routes_through_the_bridge_once_not_per_tag_plan():
    tabular = [
        _xml_plan("po_PurchaseOrder.csv", "PurchaseOrder", "po.xml"),
        _xml_plan("po_Customer.csv", "Customer", "po.xml"),
    ]
    result = _run(tabular=tabular, approved_files=["po_PurchaseOrder.csv", "po_Customer.csv"],
                  cpq_active_for={"po.xml"})

    result["bridge"].assert_called_once()
    result["project"].assert_called_once_with(XML_BYTES)


def test_cpq_active_plans_never_reach_run_pipeline_or_fk_detection():
    tabular = [
        _xml_plan("po_PurchaseOrder.csv", "PurchaseOrder", "po.xml"),
        _xml_plan("po_Customer.csv", "Customer", "po.xml"),
    ]
    result = _run(tabular=tabular, approved_files=["po_PurchaseOrder.csv", "po_Customer.csv"],
                  cpq_active_for={"po.xml"})

    result["run_pipeline"].assert_not_called()
    fk_call_plans = result["fk"].call_args.args[0]
    assert fk_call_plans == []


def test_bridge_called_with_correct_workspace_source_key_and_settings():
    tabular = [_xml_plan("po_PurchaseOrder.csv", "PurchaseOrder", "po.xml")]
    result = _run(tabular=tabular, approved_files=["po_PurchaseOrder.csv"], cpq_active_for={"po.xml"})

    _, kwargs = result["bridge"].call_args
    assert kwargs["workspace_id"] == 879
    assert kwargs["source_key"] == "po"
    assert kwargs["dsn"] == "postgresql://x"
    assert kwargs["graph_url"] == "redis://x"


def test_cpq_inactive_xml_plans_use_the_normal_csv_path_unchanged():
    """Regression guard: when the pipeline isn't active for a file, behavior
    must be byte-for-byte what it was before this wiring existed."""
    tabular = [_xml_plan("po_PurchaseOrder.csv", "PurchaseOrder", "po.xml")]
    result = _run(tabular=tabular, approved_files=["po_PurchaseOrder.csv"], cpq_active_for=set())

    result["bridge"].assert_not_called()
    result["run_pipeline"].assert_called_once()
    fk_call_plans = result["fk"].call_args.args[0]
    assert len(fk_call_plans) == 1


def test_mixed_batch_only_active_xml_file_uses_the_bridge():
    tabular = [
        _xml_plan("po_PurchaseOrder.csv", "PurchaseOrder", "po.xml"),
        _csv_plan("regular.csv", "Regular"),
    ]
    result = _run(tabular=tabular, approved_files=["po_PurchaseOrder.csv", "regular.csv"],
                  cpq_active_for={"po.xml"})

    result["bridge"].assert_called_once()
    result["run_pipeline"].assert_called_once()
    fk_call_plans = result["fk"].call_args.args[0]
    assert [p["filename"] for p in fk_call_plans] == ["regular.csv"]


def test_two_distinct_xml_source_files_each_get_their_own_bridge_call():
    tabular = [
        _xml_plan("a_Type1.csv", "Type1", "a.xml"),
        _xml_plan("a_Type2.csv", "Type2", "a.xml"),
        _xml_plan("b_Type1.csv", "Type1", "b.xml"),
    ]
    result = _run(tabular=tabular, approved_files=["a_Type1.csv", "a_Type2.csv", "b_Type1.csv"],
                  cpq_active_for={"a.xml", "b.xml"})

    assert result["bridge"].call_count == 2
    source_keys = {c.kwargs["source_key"] for c in result["bridge"].call_args_list}
    assert source_keys == {"a", "b"}


def test_tabular_sources_are_still_persisted_for_cpq_ingestion_plans():
    """The archival/catalog write for CSV bytes stays unchanged -- only the
    resolve/relate execution path differs, not what gets recorded."""
    tabular = [_xml_plan("po_PurchaseOrder.csv", "PurchaseOrder", "po.xml")]
    result = _run(tabular=tabular, approved_files=["po_PurchaseOrder.csv"], cpq_active_for={"po.xml"})

    result["persist"].assert_called_once()
    persisted_plans = result["persist"].call_args.args[0]
    assert [p["filename"] for p in persisted_plans] == ["po_PurchaseOrder.csv"]


def test_job_progress_reports_a_cpq_ingestion_stage():
    tabular = [_xml_plan("po_PurchaseOrder.csv", "PurchaseOrder", "po.xml")]
    result = _run(tabular=tabular, approved_files=["po_PurchaseOrder.csv"], cpq_active_for={"po.xml"})

    stages = [c.args[1] for c in result["jobs"].update_stage.call_args_list]
    assert "CPQ Ingestion" in stages


# ── should_stop cancellation (this confirm path's cpq loop previously
# never passed should_stop to the bridge, or checked it between files) ────

def _run_expecting_cancel(*, tabular, approved_files, cpq_active_for, jobs):
    """Same patch stack as _run(), but ingest_confirmed() is expected to
    raise PipelineCancelled -- returns the same mocks dict for inspection."""
    data = {"mentions": [], "tabular": tabular}
    with patch("aryx.pipeline.doc_discovery.doc_discovery.get_settings") as mock_settings, \
         patch("aryx.pipeline.doc_discovery.doc_discovery.DatasourceStore", return_value=MagicMock()), \
         patch("aryx.pipeline.doc_discovery.doc_discovery.run_pipeline") as mock_run_pipeline, \
         patch("aryx.pipeline.doc_discovery.doc_discovery._detect_fk_links", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._detect_script_data_flow_links", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._persist_tabular_sources"), \
         patch("aryx.cpq_ingestion.routing.cpq_ingestion_pipeline_active",
               side_effect=lambda fn: fn in cpq_active_for), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.resolve_and_relate_raw_graph",
               return_value={"tags": 2, "entities": 2, "relationships": 1}) as mock_bridge, \
         patch("aryx.cpq_ingestion.raw_graph.xml_projector.project_xml_to_raw_graph",
               return_value="PROJECTION"):
        settings_mock = MagicMock()
        settings_mock.effective_dsn.return_value = "postgresql://x"
        settings_mock.graph_url = "redis://x"
        settings_mock.ingest_workers = 1
        settings_mock.ingest_relate = True
        mock_settings.return_value = settings_mock
        with pytest.raises(PipelineCancelled):
            ingest_confirmed(
                data, [], approved_files, broker=MagicMock(),
                jobs=jobs, job_id="job-cpq-cancel", workspace_id=879,
            )
    return {"bridge": mock_bridge, "run_pipeline": mock_run_pipeline}


def test_should_stop_is_forwarded_into_resolve_and_relate_raw_graph():
    tabular = [_xml_plan("po_PurchaseOrder.csv", "PurchaseOrder", "po.xml")]
    result = _run(tabular=tabular, approved_files=["po_PurchaseOrder.csv"], cpq_active_for={"po.xml"})

    _, kwargs = result["bridge"].call_args
    assert callable(kwargs["should_stop"])


def test_pre_cancelled_job_never_calls_the_bridge_for_any_queued_source_file():
    """A job already cancelled before the cpq loop starts must not run
    resolve_and_relate_raw_graph for even the first queued XML source file
    -- previously should_stop wasn't checked here at all, so a cancel
    issued between two queued files (or before the first) had no effect
    until the whole confirm finished."""
    jobs = MagicMock()
    jobs.get.return_value = {"status": "cancelled"}
    tabular = [
        _xml_plan("a_Type1.csv", "Type1", "a.xml"),
        _xml_plan("b_Type1.csv", "Type1", "b.xml"),
    ]
    result = _run_expecting_cancel(
        tabular=tabular, approved_files=["a_Type1.csv", "b_Type1.csv"],
        cpq_active_for={"a.xml", "b.xml"}, jobs=jobs,
    )

    result["bridge"].assert_not_called()


def test_non_xml_plans_without_source_filename_are_unaffected():
    """A plan with no source_filename at all (a plain uploaded CSV, never
    derived from XML) must never even reach cpq_ingestion_pipeline_active()."""
    tabular = [_csv_plan("regular.csv", "Regular")]
    result = _run(tabular=tabular, approved_files=["regular.csv"], cpq_active_for=set())

    result["active"].assert_not_called()
    result["bridge"].assert_not_called()
    result["run_pipeline"].assert_called_once()
