"""Regression coverage for the doc-discovery / file-ingest executor split.

Raven review finding on PR #10: no test caught doc_discover_api.py silently
sharing file_ingest_api.py's executor, so when that executor became a
ProcessPoolExecutor (PR #7), the discoveries handoff broke silently — the
job still reported "complete" while the discovered types/files vanished
(see aryx.discoveries: an in-process-memory-only dict a worker process
can't share with the API process). These tests pin down both properties
that made the bug possible: (1) the two routers must never resolve to the
same executor instance/type again, and (2) a value written by a task
submitted to doc_discover_api's executor must actually be visible to the
caller afterward — the exact handoff the bug broke.
"""
from __future__ import annotations

import sys
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from unittest.mock import MagicMock, patch

# Stub heavy deps so both API modules load without installed DB packages
# (mirrors the stub list in test_job_store.py / test_migrate.py).
for _mod in ("psycopg", "psycopg.types", "psycopg.types.json",
             "falkordb", "pgvector", "pgvector.psycopg"):
    sys.modules.setdefault(_mod, MagicMock())
sys.modules.setdefault("psycopg_pool", MagicMock(ConnectionPool=MagicMock()))

import aryx.api.doc_discover_api as doc_discover_api
import aryx.api.file_ingest_api as file_ingest_api
from aryx import discoveries

_settings_stub = MagicMock(worker_threads=2)


def setup_function(_fn) -> None:
    """Patch get_settings() in both modules so _get_executor() doesn't
    depend on the real Settings() — which loads the developer's actual
    .env and fails validation on any local override key these modules
    don't declare (unrelated to what's under test here)."""
    global _patchers
    _patchers = [
        patch.object(doc_discover_api, "get_settings", return_value=_settings_stub),
        patch.object(file_ingest_api, "get_settings", return_value=_settings_stub),
    ]
    for p in _patchers:
        p.start()


def teardown_function(_fn) -> None:
    """Each module caches its executor as a module-level singleton — drain
    and reset both after every test so tests don't leak state into each
    other."""
    doc_discover_api.shutdown_executor()
    file_ingest_api.shutdown_executor()
    for p in _patchers:
        p.stop()


def test_doc_discover_executor_is_a_thread_pool():
    executor = doc_discover_api._get_executor()
    assert isinstance(executor, ThreadPoolExecutor)


def test_file_ingest_executor_is_a_process_pool():
    executor = file_ingest_api._get_executor()
    assert isinstance(executor, ProcessPoolExecutor)


def test_doc_discover_and_file_ingest_executors_are_distinct_pools():
    """The exact regression: these two must never resolve to the same
    executor again, or the discoveries handoff silently breaks."""
    docs_executor = doc_discover_api._get_executor()
    ingest_executor = file_ingest_api._get_executor()

    assert docs_executor is not ingest_executor
    assert type(docs_executor) is not type(ingest_executor)


def test_value_written_by_doc_discover_worker_is_visible_to_caller():
    """The actual handoff the bug broke: a task submitted to
    doc_discover_api's executor writes to aryx.discoveries, and the
    submitting thread must see that write once the task completes — proof
    the executor shares this process's memory instead of a worker
    process's private copy of it."""
    did = f"test-{threading.get_ident()}"
    discoveries.drop(did)

    def _worker() -> None:
        discoveries.put(did, {"summary": {"types": [{"type": "Invoice"}], "files": []}})

    future = doc_discover_api._get_executor().submit(_worker)
    future.result(timeout=5)

    result = discoveries.get(did)
    assert result is not None
    assert result["summary"]["types"] == [{"type": "Invoice"}]

    discoveries.drop(did)
