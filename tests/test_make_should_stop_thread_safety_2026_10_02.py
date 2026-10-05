"""PR #416 review: _relate_isolated's ThreadPoolExecutor is the first caller
to invoke make_should_stop's returned closure from more than one thread at
a time -- every prior caller (dimension_link, orchestrate.py's stage
boundaries) only ever called it from a single thread. Confirms the closure's
"at most one real DB read per min_interval_s" promise still holds under
concurrent callers, and that ordinary not-cancelled/cancelled behavior is
unaffected.

Moved to aryx.store.job_store (from aryx.api.file_ingest.file_ingest_run,
where it originated) so both the /admin/ingest/file path and the
Documents-tab confirm path (doc_discovery.ingest_confirmed) can share one
implementation without pipeline code importing from the api layer -- see
test_doc_discovery_ingest_confirmed_should_stop_2026_10_02.py for the
Documents-tab wiring this enabled.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from aryx.store.job_store import make_should_stop


class _FakeJobStore:
    def __init__(self, status: str = "running") -> None:
        self._status = status
        self._lock = threading.Lock()
        self.get_calls = 0

    def get(self, job_id: str) -> dict:
        with self._lock:
            self.get_calls += 1
        return {"job_id": job_id, "status": self._status}


def test_should_stop_throttles_db_reads_under_concurrent_callers():
    jobs = _FakeJobStore(status="running")
    # Large min_interval_s so every thread's call lands in the same window
    # regardless of thread-startup jitter.
    should_stop = make_should_stop(jobs, "job-1", min_interval_s=10.0)

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: should_stop(), range(20)))

    assert results == [False] * 20
    # Without the lock, up to 20 threads could all pass the throttle check
    # before any of them recorded last_check, each issuing its own
    # jobs.get() call.
    assert jobs.get_calls == 1


def test_should_stop_returns_false_when_job_is_running():
    jobs = _FakeJobStore(status="running")
    should_stop = make_should_stop(jobs, "job-1", min_interval_s=0.0)
    assert should_stop() is False


def test_should_stop_returns_true_when_job_is_cancelled():
    jobs = _FakeJobStore(status="cancelled")
    should_stop = make_should_stop(jobs, "job-1", min_interval_s=0.0)
    assert should_stop() is True


def test_should_stop_sticky_true_never_rechecks_after_cancelled():
    """Once cancelled is observed, every subsequent call must short-circuit
    on state["stopped"] -- confirmed by counting jobs.get() calls across
    several more should_stop() calls, even with min_interval_s=0.0 (which
    would otherwise re-check the DB every time)."""
    jobs = _FakeJobStore(status="cancelled")
    should_stop = make_should_stop(jobs, "job-1", min_interval_s=0.0)

    assert should_stop() is True
    assert should_stop() is True
    assert should_stop() is True
    assert jobs.get_calls == 1


def test_should_stop_returns_true_when_job_is_failed():
    """PR review M1 (2026-10-04): a job the heartbeat sweep
    (sweep_stale_heartbeat) marked 'failed' out from under a still-running
    worker must also stop that worker -- not just a user-initiated
    'cancelled'. Without this, update_job_stage.sql's own guard stops the
    DB row from being resurrected, but the worker itself keeps running
    indefinitely, duplicating or conflicting with whatever retry/re-confirm
    the operator starts after seeing the job marked failed."""
    jobs = _FakeJobStore(status="failed")
    should_stop = make_should_stop(jobs, "job-1", min_interval_s=0.0)
    assert should_stop() is True


def test_should_stop_sticky_true_never_rechecks_after_failed():
    jobs = _FakeJobStore(status="failed")
    should_stop = make_should_stop(jobs, "job-1", min_interval_s=0.0)

    assert should_stop() is True
    assert should_stop() is True
    assert jobs.get_calls == 1
