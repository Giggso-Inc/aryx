"""PR #416 review (medium finding): the Documents-tab confirm path
(doc_discover_confirm_job._confirm_job -> doc_discovery.ingest_confirmed)
built no should_stop at all, unlike the /admin/ingest/file path -- a job
cancelled here never reached the cancellation support added to
_relate_isolated/dimension_link. ingest_confirmed now builds one should_stop
(via the shared aryx.store.job_store.make_should_stop) and passes it to
every run_pipeline() call -- both the per-mention-type loop and
_run_one_plan's per-tabular-file loop.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from aryx.pipeline.doc_discovery.doc_discovery import ingest_confirmed
from aryx.pipeline.orchestrate import PipelineCancelled


def _mention(otype: str):
    return SimpleNamespace(payload={"type": otype, "name": f"{otype}-example"})


def _csv_plan(filename: str, otype: str) -> dict:
    return {
        "filename": filename, "ontology_type": otype, "match_keys": ["id"],
        "data": b"id,name\n1,Widget\n2,Gadget\n",
    }


def _run(data, approved_types, approved_files, jobs=None):
    jobs = jobs if jobs is not None else MagicMock()
    with patch("aryx.pipeline.doc_discovery.doc_discovery.get_settings") as mock_settings, \
         patch("aryx.pipeline.doc_discovery.doc_discovery.DatasourceStore", return_value=MagicMock()), \
         patch("aryx.pipeline.doc_discovery.doc_discovery.run_pipeline") as mock_run_pipeline, \
         patch("aryx.pipeline.doc_discovery.doc_discovery.OntologyStore", return_value=MagicMock()), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._detect_fk_links", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._detect_script_data_flow_links", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._detect_fk_links_workspace", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.doc_discovery.detect_dynamic_fk_links", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._persist_tabular_sources"), \
         patch("aryx.pipeline.doc_discovery.doc_discovery.restore_generic_source_entry"):
        settings_mock = MagicMock()
        settings_mock.rdb_dsn = "postgresql://x"
        settings_mock.graph_url = "redis://x"
        settings_mock.ingest_workers = 1
        settings_mock.ingest_relate = True
        settings_mock.fk_dynamic_progress_report_min_interval_s = 2.0
        mock_settings.return_value = settings_mock
        ingest_confirmed(data, approved_types, approved_files, broker=MagicMock(),
                         jobs=jobs, job_id="job-1", workspace_id=1)
    return mock_run_pipeline


def test_mention_type_loop_passes_should_stop_to_run_pipeline():
    data = {"mentions": [_mention("Strategy"), _mention("Metric")], "tabular": []}
    mock_run_pipeline = _run(data, ["Strategy", "Metric"], [])

    assert mock_run_pipeline.call_count == 2
    for call in mock_run_pipeline.call_args_list:
        assert callable(call.kwargs["should_stop"])
    # Same closure reused across every call in one ingest_confirmed run --
    # one should_stop per confirm job, not one per type/file.
    should_stops = {call.kwargs["should_stop"] for call in mock_run_pipeline.call_args_list}
    assert len(should_stops) == 1


def test_tabular_plan_loop_passes_should_stop_to_run_pipeline():
    data = {"mentions": [], "tabular": [_csv_plan("a.csv", "A"), _csv_plan("b.csv", "B")]}
    mock_run_pipeline = _run(data, [], ["a.csv", "b.csv"])

    assert mock_run_pipeline.call_count == 2
    for call in mock_run_pipeline.call_args_list:
        assert callable(call.kwargs["should_stop"])


def test_should_stop_is_false_when_job_is_running():
    """Not a stub -- confirms ingest_confirmed wires in the actual
    aryx.store.job_store.make_should_stop, which is what gives the
    Documents-tab path the same cancellation behavior as /admin/ingest/file
    (including the thread-safety fix for _relate_isolated's worker pool).
    A fresh should_stop per test avoids the real throttle (min_interval_s=1)
    making a second call on the same closure flaky against wall-clock time."""
    jobs = MagicMock()
    jobs.get.return_value = {"status": "running"}
    data = {"mentions": [_mention("Strategy")], "tabular": []}
    mock_run_pipeline = _run(data, ["Strategy"], [], jobs=jobs)

    should_stop = mock_run_pipeline.call_args.kwargs["should_stop"]
    assert should_stop() is False


def test_should_stop_is_true_when_job_is_cancelled():
    jobs = MagicMock()
    jobs.get.return_value = {"status": "cancelled"}
    data = {"mentions": [_mention("Strategy")], "tabular": []}
    mock_run_pipeline = _run(data, ["Strategy"], [], jobs=jobs)

    should_stop = mock_run_pipeline.call_args.kwargs["should_stop"]
    assert should_stop() is True


def test_cancellation_mid_nonlast_plan_propagates_and_skips_the_last_plan():
    """PR #416 review (medium finding): non-last plans run in a
    ThreadPoolExecutor, and the as_completed loop's exception handler used
    to be a single bare `except Exception` -- a PipelineCancelled from a
    non-last plan was logged as "plan failed" with a stack trace, and the
    loop just continued on. a.csv's run_pipeline raises PipelineCancelled;
    the as_completed handler must now re-raise (after shutting the pool
    down with cancel_futures=True to abandon whatever's still queued)
    instead of swallowing it as a generic failure.

    What's deterministically testable here (and isn't racy against the
    ThreadPoolExecutor's own worker-vs-main-thread scheduling, unlike
    exactly how many OTHER non-last plans the cancel_futures abandonment
    manages to catch in time): the exception reaches the caller rather than
    being logged-and-continued, and the serial "last" plan (c.csv, which
    only runs via sequential code AFTER the entire non-last block returns)
    is never reached at all."""
    def _fake_run_pipeline(*args, **kwargs):
        if kwargs.get("dataset") == "a":
            raise PipelineCancelled("job cancelled")
        return None

    data = {"mentions": [], "tabular": [
        _csv_plan("a.csv", "A"), _csv_plan("b.csv", "B"), _csv_plan("c.csv", "C"),
    ]}
    jobs = MagicMock()
    with patch("aryx.pipeline.doc_discovery.doc_discovery.get_settings") as mock_settings, \
         patch("aryx.pipeline.doc_discovery.doc_discovery.DatasourceStore", return_value=MagicMock()), \
         patch("aryx.pipeline.doc_discovery.doc_discovery.run_pipeline",
               side_effect=_fake_run_pipeline) as mock_run_pipeline, \
         patch("aryx.pipeline.doc_discovery.doc_discovery.OntologyStore", return_value=MagicMock()), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._detect_fk_links", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._detect_script_data_flow_links", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._detect_fk_links_workspace", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.doc_discovery.detect_dynamic_fk_links", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._persist_tabular_sources"), \
         patch("aryx.pipeline.doc_discovery.doc_discovery.restore_generic_source_entry"):
        settings_mock = MagicMock()
        settings_mock.rdb_dsn = "postgresql://x"
        settings_mock.graph_url = "redis://x"
        settings_mock.ingest_workers = 1
        settings_mock.ingest_relate = True
        settings_mock.fk_dynamic_progress_report_min_interval_s = 2.0
        mock_settings.return_value = settings_mock
        with pytest.raises(PipelineCancelled):
            ingest_confirmed(data, [], ["a.csv", "b.csv", "c.csv"], broker=MagicMock(),
                             jobs=jobs, job_id="job-1", workspace_id=1)

    called_datasets = [c.kwargs["dataset"] for c in mock_run_pipeline.call_args_list]
    assert "a" in called_datasets
    # c.csv is the serial "last" plan -- reaching it at all would mean the
    # PipelineCancelled above was swallowed rather than propagated.
    assert "c" not in called_datasets
