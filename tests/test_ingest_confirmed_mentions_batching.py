"""ingest_confirmed()'s mention-type loop: relate/skip_graph must follow the
same is_last pattern already proven for tabular plans (_run_one_plan).

Real incident: a 96-mention-type PDF batch ran relate, schema_fk,
relate_isolated, dimension_link, AND a full graph clear()+rebuild on EVERY
type — project_graph's own contract is to rebuild the entire workspace graph
from every entity seen so far, so cost grew with every type instead of
running once, turning a ~40-minute extraction into a 3+ hour ingest. Only
the LAST type with any mentions should run the expensive whole-workspace
passes; earlier types should just resolve their own records.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aryx.pipeline.doc_discovery import ingest_confirmed


def _mention(otype: str):
    return SimpleNamespace(payload={"type": otype, "name": f"{otype}-example"})


def _run(approved_types, mentions):
    data = {"mentions": mentions, "tabular": []}
    jobs = MagicMock()
    with patch("aryx.pipeline.doc_discovery.get_settings") as mock_settings, \
         patch("aryx.pipeline.doc_discovery.DatasourceStore", return_value=MagicMock()), \
         patch("aryx.pipeline.doc_discovery.run_pipeline") as mock_run_pipeline, \
         patch("aryx.pipeline.doc_discovery.OntologyStore", return_value=MagicMock()), \
         patch("aryx.pipeline.doc_discovery._detect_fk_links", return_value=[]), \
         patch("aryx.pipeline.doc_discovery._detect_script_data_flow_links", return_value=[]), \
         patch("aryx.pipeline.doc_discovery._detect_fk_links_workspace", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.detect_dynamic_fk_links", return_value=[]), \
         patch("aryx.pipeline.doc_discovery._persist_tabular_sources"):
        settings_mock = MagicMock()
        settings_mock.rdb_dsn = "postgresql://x"
        settings_mock.graph_url = "redis://x"
        settings_mock.ingest_workers = 1
        settings_mock.ingest_relate = True
        mock_settings.return_value = settings_mock
        ingest_confirmed(data, approved_types, [], broker=MagicMock(),
                         jobs=jobs, job_id="job-1", workspace_id=1)
    return mock_run_pipeline


def test_only_the_last_type_with_mentions_runs_relate_and_projects_graph():
    mentions = [_mention("Strategy"), _mention("Metric"), _mention("KPI")]
    mock_run_pipeline = _run(["Strategy", "Metric", "KPI"], mentions)

    assert mock_run_pipeline.call_count == 3
    first, second, last = mock_run_pipeline.call_args_list
    assert first.kwargs["relate"] is False
    assert first.kwargs["skip_graph"] is True
    assert second.kwargs["relate"] is False
    assert second.kwargs["skip_graph"] is True
    assert last.kwargs["relate"] is True
    assert last.kwargs["skip_graph"] is False


def test_last_type_is_the_last_one_that_actually_has_mentions():
    """A type with zero mentions must not be counted when picking is_last —
    it never calls run_pipeline at all, so it can't be the one that runs
    the whole-workspace passes."""
    mentions = [_mention("Strategy"), _mention("Metric")]
    # "KPI" is approved but has no matching mentions in this batch.
    mock_run_pipeline = _run(["Strategy", "Metric", "KPI"], mentions)

    assert mock_run_pipeline.call_count == 2
    first, last = mock_run_pipeline.call_args_list
    assert first.kwargs["relate"] is False
    assert first.kwargs["skip_graph"] is True
    assert last.kwargs["relate"] is True
    assert last.kwargs["skip_graph"] is False
    assert last.kwargs["dataset"] == "Metric"


def test_single_type_batch_still_relates_and_projects():
    mentions = [_mention("Strategy")]
    mock_run_pipeline = _run(["Strategy"], mentions)

    assert mock_run_pipeline.call_count == 1
    only_call = mock_run_pipeline.call_args_list[0]
    assert only_call.kwargs["relate"] is True
    assert only_call.kwargs["skip_graph"] is False
