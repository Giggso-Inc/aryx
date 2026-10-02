"""Bounded per-key tables-cache lock (dev-rv-msi #368 Part B / #371)."""
from __future__ import annotations

import logging
import threading
import time
from unittest.mock import patch

import pytest

from aryx.config import get_settings
from aryx.cpq.data_table import data_table_loader as ldr


@pytest.fixture(autouse=True)
def _isolate():
    s = get_settings()
    prev = (s.cpq_tables_cache_lock_enabled, s.cpq_tables_cache_lock_timeout_s)
    ldr._TABLES_CACHE.clear()
    ldr._TABLES_CACHE_LOCKS.clear()
    yield
    s.cpq_tables_cache_lock_enabled, s.cpq_tables_cache_lock_timeout_s = prev
    ldr._TABLES_CACHE.clear()
    ldr._TABLES_CACHE_LOCKS.clear()


class _FakeRdb:
    def __init__(self, delay: float = 0.0):
        self.calls = 0
        self.delay = delay

    def fetch_all_entities_grouped_by_type(self, workspace_id):
        self.calls += 1
        time.sleep(self.delay)
        # one constraint-shaped row so the scan is non-empty (an all-empty scan
        # is deliberately not stored in the module cache)
        return {"Whitelist": [(1, {"CPQModel": "M", "BaseModel": "B", "attr1": "a", "val1": "v"})]}


def _run_concurrently(n: int, key=(1, "p")):
    threads = [
        threading.Thread(target=ldr._load_all_tables, args=key) for _ in range(n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not any(t.is_alive() for t in threads)


def test_lock_serialises_and_second_load_hits_cache():
    get_settings().cpq_tables_cache_lock_enabled = True
    rdb = _FakeRdb(delay=0.3)
    with patch.object(ldr, "get_cpq_rdb", return_value=rdb), \
         patch.object(ldr, "_invalidate_on_marker_change", return_value=None):
        _run_concurrently(4)
    assert rdb.calls == 1


def test_flag_off_no_lock_concurrent_scans():
    get_settings().cpq_tables_cache_lock_enabled = False
    rdb = _FakeRdb(delay=0.3)
    with patch.object(ldr, "get_cpq_rdb", return_value=rdb), \
         patch.object(ldr, "_invalidate_on_marker_change", return_value=None):
        _run_concurrently(3)
    assert rdb.calls == 3
    assert ldr._TABLES_CACHE_LOCKS == {}


def test_lock_timeout_logs_warning_and_scans_unlocked(caplog):
    s = get_settings()
    s.cpq_tables_cache_lock_enabled = True
    s.cpq_tables_cache_lock_timeout_s = 0.2
    key = (2, "p")
    held = ldr._tables_cache_lock(key)
    held.acquire()  # simulate a stalled scan
    rdb = _FakeRdb()
    try:
        with patch.object(ldr, "get_cpq_rdb", return_value=rdb), \
             patch.object(ldr, "_invalidate_on_marker_change", return_value=None), \
             caplog.at_level(logging.WARNING, logger=ldr.logger.name):
            ldr._load_all_tables(*key)
        assert rdb.calls == 1
        assert any(
            r.levelno == logging.WARNING and "TIMED OUT" in r.getMessage()
            for r in caplog.records
        )
        assert held.locked(), "timed-out waiter must not release a lock it never held"
    finally:
        held.release()


def test_bounded_lock_uncontended_acquires_and_releases():
    key = (3, "p")
    with ldr._bounded_tables_cache_lock(key, 0.2) as acquired:
        assert acquired is True
        assert ldr._tables_cache_lock(key).locked()
    assert not ldr._tables_cache_lock(key).locked()


def test_bounded_lock_waiter_times_out_instead_of_hanging():
    key = (4, "p")
    lock = ldr._tables_cache_lock(key)
    lock.acquire()
    try:
        result: dict[str, bool] = {}

        def _waiter():
            with ldr._bounded_tables_cache_lock(key, 0.2) as acquired:
                result["acquired"] = acquired

        t = threading.Thread(target=_waiter)
        t.start()
        t.join(timeout=5)
        assert not t.is_alive()
        assert result["acquired"] is False
        assert lock.locked()
    finally:
        lock.release()


def test_bounded_lock_releases_when_body_raises():
    key = (5, "p")
    with pytest.raises(RuntimeError):
        with ldr._bounded_tables_cache_lock(key, 0.2):
            raise RuntimeError("scan failed")
    assert not ldr._tables_cache_lock(key).locked()
