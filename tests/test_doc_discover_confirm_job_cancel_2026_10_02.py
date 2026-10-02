"""PR #416 review (medium finding): once ingest_confirmed actually threads
should_stop through to run_pipeline() (see
test_doc_discovery_ingest_confirmed_should_stop_2026_10_02.py), a cancelled
confirm job raises PipelineCancelled out of run_pipeline() at the next stage
boundary. _confirm_job's only exception handler used to be a single broad
`except Exception`, which would have caught that and overwritten the job's
already-correct "cancelled" status with "failed" -- the exact bug
file_ingest_run.py's own PipelineCancelled handler already exists to avoid
on the /admin/ingest/file path.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.api.doc_discover.doc_discover_confirm_job import _confirm_job
from aryx.pipeline.orchestrate import PipelineCancelled


def _run(ingest_confirmed_side_effect, jobs=None):
    jobs = jobs if jobs is not None else MagicMock()
    with patch("aryx.api.doc_discover.doc_discover_confirm_job.JobStore", return_value=jobs), \
         patch("aryx.api.doc_discover.doc_discover_confirm_job.get_settings") as mock_settings, \
         patch("aryx.api.doc_discover.doc_discover_confirm_job.discoveries") as mock_discoveries, \
         patch("aryx.api.doc_discover.doc_discover_confirm_job._local_broker", return_value=MagicMock()), \
         patch("aryx.api.doc_discover.doc_discover_confirm_job.ingest_confirmed",
               side_effect=ingest_confirmed_side_effect) as mock_ingest, \
         patch("aryx.api.doc_discover.doc_discover_confirm_job._reset_discovery_status") as mock_reset:
        mock_settings.return_value.effective_dsn.return_value = "postgresql://x"
        mock_discoveries.get.return_value = {"mentions": [], "tabular": []}
        _confirm_job("did-1", ["A"], [], job_id="job-1", workspace_id=1)
    return jobs, mock_discoveries, mock_ingest, mock_reset


def test_cancelled_confirm_does_not_overwrite_job_status_to_failed():
    jobs, mock_discoveries, _, mock_reset = _run(PipelineCancelled("job cancelled"))

    jobs.finish.assert_not_called()
    mock_discoveries.mark_confirmed.assert_not_called()
    mock_reset.assert_called_once_with("did-1")


def test_cancelled_confirm_resets_discovery_to_partial_not_failed_only():
    """Distinguishes the cancel path from the genuine-failure path: both
    reset the discovery (so it isn't permanently stuck), but only the
    genuine-failure path also calls jobs.finish(status="failed")."""
    _run(PipelineCancelled("job cancelled"))  # smoke: must not raise

    jobs, _, _, mock_reset = _run(RuntimeError("boom"))
    jobs.finish.assert_called_once_with("job-1", run_id=None, status="failed", error="boom")
    mock_reset.assert_called_once_with("did-1")


def test_successful_confirm_finishes_and_marks_confirmed_normally():
    jobs, mock_discoveries, _, mock_reset = _run(None)

    jobs.finish.assert_called_once_with("job-1", run_id=None, status="complete")
    mock_discoveries.mark_confirmed.assert_called_once_with("did-1", "job-1")
    mock_reset.assert_not_called()
