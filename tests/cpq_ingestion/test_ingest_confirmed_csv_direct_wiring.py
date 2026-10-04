"""ingest_confirmed()'s cpq_ingestion CSV wiring: a plain CSV upload flagged
cpq_csv_direct (by read_files(), when ARYX_INGEST_FILE_TYPE includes "csv")
lands directly in Postgres via land_csv_directly() and is excluded from the
generic CSV pipeline (FK detection + _run_one_plan/run_pipeline +
_persist_tabular_sources), so it never touches the knowledge graph at all.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.pipeline.doc_discovery.doc_discovery import ingest_confirmed


def _csv_plan(filename: str, otype: str, *, cpq_csv_direct: bool = False) -> dict:
    plan = {
        "filename": filename, "ontology_type": otype, "match_keys": ["id"],
        "data": b"id,name\n1,Widget\n",
    }
    if cpq_csv_direct:
        plan["cpq_csv_direct"] = True
    return plan


def _run(*, tabular, approved_files, job_id="job-csv-wiring", jobs=None,
         land_result=None):
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
         patch("aryx.cpq_ingestion.csv_land.land_csv_directly",
               return_value=land_result or {"run_id": 1, "source_key": "catalog", "rows_landed": 2},
               ) as mock_land:
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
        "persist": mock_persist, "land": mock_land, "settings": settings_mock,
    }


def test_flagged_csv_plan_routes_through_land_csv_directly():
    tabular = [_csv_plan("catalog.csv", "Catalog", cpq_csv_direct=True)]
    result = _run(tabular=tabular, approved_files=["catalog.csv"])

    result["land"].assert_called_once()
    args, kwargs = result["land"].call_args
    assert args[0] == b"id,name\n1,Widget\n"
    assert args[1] == "catalog"
    assert kwargs["workspace_id"] == 879
    assert kwargs["dsn"] == "postgresql://x"


def test_flagged_csv_plan_never_reaches_run_pipeline_or_fk_detection():
    tabular = [_csv_plan("catalog.csv", "Catalog", cpq_csv_direct=True)]
    result = _run(tabular=tabular, approved_files=["catalog.csv"])

    result["run_pipeline"].assert_not_called()
    fk_call_plans = result["fk"].call_args.args[0]
    assert fk_call_plans == []


def test_flagged_csv_plan_excluded_from_persist_tabular_sources():
    tabular = [_csv_plan("catalog.csv", "Catalog", cpq_csv_direct=True)]
    result = _run(tabular=tabular, approved_files=["catalog.csv"])

    persisted_plans = result["persist"].call_args.args[0]
    assert persisted_plans == []


def test_unflagged_csv_plan_uses_the_normal_pipeline_unchanged():
    """Regression guard: a CSV plan with no cpq_csv_direct flag (the
    default -- pipeline inactive, or file type doesn't include csv) must
    behave exactly as before this feature existed."""
    tabular = [_csv_plan("regular.csv", "Regular", cpq_csv_direct=False)]
    result = _run(tabular=tabular, approved_files=["regular.csv"])

    result["land"].assert_not_called()
    result["run_pipeline"].assert_called_once()
    persisted_plans = result["persist"].call_args.args[0]
    assert [p["filename"] for p in persisted_plans] == ["regular.csv"]


def test_mixed_batch_only_flagged_plan_lands_directly():
    tabular = [
        _csv_plan("catalog.csv", "Catalog", cpq_csv_direct=True),
        _csv_plan("regular.csv", "Regular", cpq_csv_direct=False),
    ]
    result = _run(tabular=tabular, approved_files=["catalog.csv", "regular.csv"])

    result["land"].assert_called_once()
    result["run_pipeline"].assert_called_once()
    fk_call_plans = result["fk"].call_args.args[0]
    assert [p["filename"] for p in fk_call_plans] == ["regular.csv"]


def test_two_flagged_csv_plans_each_get_their_own_land_call():
    tabular = [
        _csv_plan("a.csv", "A", cpq_csv_direct=True),
        _csv_plan("b.csv", "B", cpq_csv_direct=True),
    ]
    result = _run(tabular=tabular, approved_files=["a.csv", "b.csv"])

    assert result["land"].call_count == 2
    stems = {c.args[1] for c in result["land"].call_args_list}
    assert stems == {"a", "b"}


def test_job_progress_reports_a_cpq_ingestion_stage_for_csv():
    tabular = [_csv_plan("catalog.csv", "Catalog", cpq_csv_direct=True)]
    result = _run(tabular=tabular, approved_files=["catalog.csv"])

    stages = [c.args[1] for c in result["jobs"].update_stage.call_args_list]
    assert "CPQ Ingestion" in stages


def test_csv_direct_plan_survives_a_failure_in_a_prior_csv_direct_plan():
    """High-severity regression guard: one bad CSV file in a multi-file
    confirm batch must not abort the rest -- mirrors the layout_plans
    loop's existing per-file try/except immediately above this one."""
    tabular = [
        _csv_plan("broken.csv", "Broken", cpq_csv_direct=True),
        _csv_plan("catalog.csv", "Catalog", cpq_csv_direct=True),
    ]
    jobs = MagicMock()
    data = {"mentions": [], "tabular": tabular}
    with patch("aryx.pipeline.doc_discovery.doc_discovery.get_settings") as mock_settings, \
         patch("aryx.pipeline.doc_discovery.doc_discovery.DatasourceStore", return_value=MagicMock()), \
         patch("aryx.pipeline.doc_discovery.doc_discovery.run_pipeline"), \
         patch("aryx.pipeline.doc_discovery.doc_discovery.OntologyStore", return_value=MagicMock()), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._detect_fk_links", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._detect_script_data_flow_links", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._detect_fk_links_workspace", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._persist_tabular_sources"), \
         patch("aryx.pipeline.doc_discovery.doc_discovery.restore_generic_source_entry"), \
         patch("aryx.pipeline.doc_discovery.doc_discovery.detect_dynamic_fk_links", return_value=[]), \
         patch(
             "aryx.cpq_ingestion.csv_land.land_csv_directly",
             side_effect=[
                 RuntimeError("boom"),
                 {"run_id": 1, "source_key": "catalog", "rows_landed": 2},
             ],
         ) as mock_land:
        settings_mock = MagicMock()
        settings_mock.effective_dsn.return_value = "postgresql://x"
        settings_mock.graph_url = "redis://x"
        settings_mock.ingest_workers = 1
        settings_mock.ingest_relate = True
        mock_settings.return_value = settings_mock
        ingest_confirmed(
            data, [], ["broken.csv", "catalog.csv"], broker=MagicMock(),
            jobs=jobs, job_id="job-csv-partial-failure", workspace_id=879,
        )

    assert mock_land.call_count == 2
    stems = [c.args[1] for c in mock_land.call_args_list]
    assert stems == ["broken", "catalog"]


def test_xml_and_csv_direct_plans_coexist_in_one_batch():
    """Medium-severity coverage gap: an XML-derived plan (routed through the
    raw-graph resolve/relate bridge) and a cpq_csv_direct-flagged plain CSV
    plan (routed through land_csv_directly) in the SAME confirm batch must
    each reach their own destination without interfering with each other or
    with the generic CSV pipeline."""
    xml_plan = {
        "filename": "po_PurchaseOrder.csv", "ontology_type": "PurchaseOrder",
        "match_keys": ["_text"], "data": b"Id\nPO-1\n",
        "source_filename": "po.xml",
        "source_bytes": b"<PurchaseOrder Id='PO-1'/>",
    }
    csv_direct_plan = _csv_plan("catalog.csv", "Catalog", cpq_csv_direct=True)
    tabular = [xml_plan, csv_direct_plan]
    jobs = MagicMock()
    data = {"mentions": [], "tabular": tabular}
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
               side_effect=lambda fn: fn == "po.xml") as mock_active, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.resolve_and_relate_raw_graph",
               return_value={"tags": 1, "entities": 1, "relationships": 0}) as mock_bridge, \
         patch("aryx.cpq_ingestion.raw_graph.xml_projector.project_xml_to_raw_graph",
               return_value="PROJECTION") as mock_project, \
         patch("aryx.cpq_ingestion.csv_land.land_csv_directly",
               return_value={"run_id": 1, "source_key": "catalog", "rows_landed": 2},
               ) as mock_land:
        settings_mock = MagicMock()
        settings_mock.effective_dsn.return_value = "postgresql://x"
        settings_mock.graph_url = "redis://x"
        settings_mock.ingest_workers = 1
        settings_mock.ingest_relate = True
        mock_settings.return_value = settings_mock
        ingest_confirmed(
            data, [], ["po_PurchaseOrder.csv", "catalog.csv"], broker=MagicMock(),
            jobs=jobs, job_id="job-mixed-xml-csv", workspace_id=879,
        )

    mock_bridge.assert_called_once()
    mock_project.assert_called_once()
    project_args, project_kwargs = mock_project.call_args
    assert project_args == (b"<PurchaseOrder Id='PO-1'/>",)
    assert callable(project_kwargs["should_stop"])
    mock_land.assert_called_once()
    land_args, land_kwargs = mock_land.call_args
    assert land_args[1] == "catalog"
    assert land_kwargs["workspace_id"] == 879

    # Neither path leaks into the generic pipeline or FK detection.
    mock_run_pipeline.assert_not_called()
    fk_call_plans = mock_fk.call_args.args[0]
    assert fk_call_plans == []
    persisted_plans = mock_persist.call_args.args[0]
    assert [p["filename"] for p in persisted_plans] == ["po_PurchaseOrder.csv"]
