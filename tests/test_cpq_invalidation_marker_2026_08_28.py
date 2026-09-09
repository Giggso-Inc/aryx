"""Cross-process cache invalidation marker (PR #287 review, Section 12 of
the concurrency-delay report). Under a single api worker process,
ingest_confirmed's in-process cache.clear() calls were sufficient to keep
the CPQ rule/table caches safe against a mid-session re-ingest. P1
(multi-worker uvicorn, same PR) broke that assumption: a re-ingest handled
by one worker never reaches another worker's independent in-memory cache
copy. This file tests the fix -- a shared invalidated_at timestamp in
Postgres (migration 0040), polled at most once per
_INVALIDATION_MARKER_POLL_SECONDS per process, that lets every OTHER
worker notice a re-ingest it didn't itself handle.

2026-08-29: a real regression was caught during implementation --
tests/test_pool.py's own sys.modules.setdefault("psycopg_pool", ...) (an
unrelated, pre-existing global mock, module-level not test-scoped) can
leak into aryx.store.pool.ConnectionPool for the WHOLE pytest process if
test_pool.py is collected before anything else really imports
psycopg_pool. Before this fix, nothing in a plain CPQ unit-test run ever
called get_pool() with the real production DSN, so that leak was latent
and harmless. This module's marker-fetch was the first thing to do so
unconditionally on every cache read, exposing it: the mocked pool made
the whole connection/cursor chain "succeed" instead of raising, so
row[0].timestamp() returned a MagicMock instead of a float, and comparing
two of those in _invalidate_on_marker_change raised an uncaught
TypeError, breaking ~150 unrelated tests. Fixed with an explicit
isinstance check in _fetch_invalidation_marker_from_db (the one place
real data enters this module) plus a defense-in-depth try/except around
the comparison itself in _invalidate_on_marker_change. test_regression_
type_safety_against_a_poisoned_pool below reproduces the exact scenario.

All other tests here fully mock the DB fetch -- none open a real
connection (unlike the module's own fail-open production behavior, which
does; see _fetch_invalidation_marker_from_db's own docstring for why a
short explicit acquisition timeout is required there).
"""
from __future__ import annotations

from unittest.mock import patch

import aryx.cpq.data_table.data_table_cache as dtc
import aryx.cpq.data_table.data_table_loader as dtl
import aryx.cpq.data_table.data_table_resolver as dtr


def setup_function(_fn):
    dtc._clear_invalidation_marker_poll_cache()


def teardown_function(_fn):
    dtc._clear_invalidation_marker_poll_cache()


# ── _current_invalidation_marker: poll-interval throttling ────────────────

def test_marker_is_polled_once_then_cached_within_the_interval():
    with patch.object(dtc, "_fetch_invalidation_marker_from_db", return_value=100.0) as mock_fetch:
        first = dtc._current_invalidation_marker()
        second = dtc._current_invalidation_marker()
    assert first == second == 100.0
    assert mock_fetch.call_count == 1, (
        "a second call within the poll interval must reuse the cached "
        f"marker, not re-fetch -- got {mock_fetch.call_count} fetches"
    )


def test_marker_is_refetched_after_the_poll_interval_elapses():
    with patch.object(dtc, "_fetch_invalidation_marker_from_db", side_effect=[100.0, 200.0]) as mock_fetch:
        dtc._current_invalidation_marker()
        checked_at, marker_ts = dtc._INVALIDATION_MARKER_POLL_CACHE
        dtc._INVALIDATION_MARKER_POLL_CACHE = (
            checked_at - dtc._INVALIDATION_MARKER_POLL_SECONDS - 1.0, marker_ts,
        )
        second = dtc._current_invalidation_marker()
    assert second == 200.0
    assert mock_fetch.call_count == 2


# ── Fail-open behavior ──────────────────────────────────────────────────

def test_fetch_failure_returns_none_and_does_not_raise():
    with patch.object(dtc, "_fetch_invalidation_marker_from_db", return_value=None):
        result = dtc._current_invalidation_marker()
    assert result is None


def test_fetch_failure_schedules_a_shorter_retry_than_a_healthy_poll():
    with patch.object(dtc, "_fetch_invalidation_marker_from_db", return_value=None):
        dtc._current_invalidation_marker()
    checked_at, marker_ts = dtc._INVALIDATION_MARKER_POLL_CACHE
    assert marker_ts is None
    import time
    remaining = dtc._INVALIDATION_MARKER_POLL_SECONDS - (time.monotonic() - checked_at)
    assert remaining <= dtc._INVALIDATION_MARKER_FAIL_RETRY_SECONDS + 0.5, (
        f"expected the next retry to be due within ~{dtc._INVALIDATION_MARKER_FAIL_RETRY_SECONDS}s, "
        f"but {remaining:.2f}s remain on the poll interval"
    )


# ── Regression: a "successful" fetch that returns garbage, not None ─────

def test_fetch_rejects_a_non_numeric_result_instead_of_returning_it():
    """The exact live-confirmed regression (2026-08-29): a poisoned/mocked
    pool can make the whole connection chain succeed without raising,
    returning a non-numeric object (a MagicMock, in the real incident)
    instead of a float. _fetch_invalidation_marker_from_db must reject
    this at the source, not pass it through as if it were a real
    timestamp."""
    class _FakeRow:
        def __getitem__(self, idx):
            return self

        def timestamp(self):
            return object()  # not None, not a real exception -- just garbage

    class _FakeCursor:
        def execute(self, *a, **k):
            pass

        def fetchone(self):
            return _FakeRow()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _FakeConnCM:
        def __enter__(self):
            return _FakeConn()

        def __exit__(self, *a):
            return False

    class _FakePool:
        def connection(self, timeout=None):
            return _FakeConnCM()

    with patch("aryx.store.pool.get_pool", return_value=_FakePool()):
        result = dtc._fetch_invalidation_marker_from_db()
    assert result is None, (
        "a non-numeric 'successful' fetch result must be treated as "
        f"unavailable (None), not passed through -- got {result!r}"
    )


def test_invalidate_on_marker_change_never_raises_on_a_bad_comparison():
    """Defense in depth: even if a non-numeric marker somehow bypasses
    _fetch_invalidation_marker_from_db's own type check, the comparison
    in _invalidate_on_marker_change must degrade to a no-op, never crash
    the real cache read it only gates."""
    cache = {"k": "v"}
    holder: list = ["not-a-number"]
    with patch.object(dtc, "_current_invalidation_marker", return_value=object()):
        dtc._invalidate_on_marker_change(cache, holder)  # must not raise
    assert cache == {"k": "v"}


# ── _invalidate_on_marker_change ────────────────────────────────────────

def test_first_observation_initializes_without_clearing():
    cache = {"k": "v"}
    holder: list[float | None] = [None]
    with patch.object(dtc, "_current_invalidation_marker", return_value=100.0):
        dtc._invalidate_on_marker_change(cache, holder)
    assert cache == {"k": "v"}, "the very first observation must not clear -- nothing to compare against yet"
    assert holder[0] == 100.0


def test_unchanged_marker_does_not_clear():
    cache = {"k": "v"}
    holder: list[float | None] = [100.0]
    with patch.object(dtc, "_current_invalidation_marker", return_value=100.0):
        dtc._invalidate_on_marker_change(cache, holder)
    assert cache == {"k": "v"}


def test_newer_marker_clears_the_whole_cache():
    cache = {"k": "v", "k2": "v2"}
    holder: list[float | None] = [100.0]
    with patch.object(dtc, "_current_invalidation_marker", return_value=200.0):
        dtc._invalidate_on_marker_change(cache, holder)
    assert cache == {}
    assert holder[0] == 200.0


def test_older_or_equal_marker_does_not_clear():
    cache = {"k": "v"}
    holder: list[float | None] = [200.0]
    with patch.object(dtc, "_current_invalidation_marker", return_value=150.0):
        dtc._invalidate_on_marker_change(cache, holder)
    assert cache == {"k": "v"}
    assert holder[0] == 200.0


def test_none_marker_is_a_complete_noop():
    cache = {"k": "v"}
    holder: list[float | None] = [100.0]
    with patch.object(dtc, "_current_invalidation_marker", return_value=None):
        dtc._invalidate_on_marker_change(cache, holder)
    assert cache == {"k": "v"}
    assert holder[0] == 100.0


# ── End-to-end proof: the real call site, not just the shared helper ────

# ── _cache_write_if_marker_unchanged (raven review, PR #290 follow-up) ──
#
# Root cause: call_tool's _dispatch now runs via asyncio.to_thread (a real
# thread-pool worker), so two MCP tool calls can genuinely interleave inside
# these caches for the first time -- previously _dispatch ran inline on the
# single event-loop thread with no `await` inside it, so interleaving here
# was impossible regardless of concurrent SSE session count. Without this
# guard: thread A reads a cache miss under marker M1 and starts a slow
# compute; thread B observes marker M2 and clears the cache; thread A
# finishes and writes its M1-computed (now stale) result back into the
# just-cleared cache under a fresh timestamp -- silently serving stale CPQ
# data for a full TTL window despite the invalidation signal having fired.

def test_write_proceeds_when_marker_is_unchanged_since_the_read():
    cache: dict = {}
    with patch.object(dtc, "_current_invalidation_marker", return_value=100.0):
        dtc._cache_write_if_marker_unchanged(cache, "k", "fresh-value", 100.0)
    assert cache == {"k": "fresh-value"}


def test_write_is_skipped_when_marker_advanced_during_the_compute():
    """The exact race: this thread read/computed under marker 100.0, but by
    the time it's ready to write, the marker has moved to 200.0 -- meaning
    another thread already cleared the cache for a real reason. Writing
    anyway would resurrect a stale value under a fresh timestamp."""
    cache: dict = {}
    with patch.object(dtc, "_current_invalidation_marker", return_value=200.0):
        dtc._cache_write_if_marker_unchanged(cache, "k", "stale-value", 100.0)
    assert cache == {}, "a write racing a concurrent invalidation must not repopulate the cache"


def test_write_is_skipped_when_marker_became_unavailable_mid_compute():
    cache: dict = {}
    with patch.object(dtc, "_current_invalidation_marker", return_value=None):
        dtc._cache_write_if_marker_unchanged(cache, "k", "stale-value", 100.0)
    assert cache == {}


def test_invalidate_on_marker_change_returns_the_observed_marker():
    """Callers depend on this return value to later detect a concurrent
    invalidation via _cache_write_if_marker_unchanged."""
    cache: dict = {}
    holder: list[float | None] = [None]
    with patch.object(dtc, "_current_invalidation_marker", return_value=100.0):
        first = dtc._invalidate_on_marker_change(cache, holder)
    assert first == 100.0
    with patch.object(dtc, "_current_invalidation_marker", return_value=200.0):
        second = dtc._invalidate_on_marker_change(cache, holder)
    assert second == 200.0


def test_end_to_end_concurrent_invalidation_does_not_resurrect_stale_data():
    """Simulates the full race at a real call site (_load_all_tables):
    thread A's read-time marker capture (_invalidate_on_marker_change,
    called once at the top of _load_all_tables) observes 100.0; by the
    time A reaches its write (_cache_write_if_marker_unchanged, called
    once after the "compute"), a concurrent thread-pool worker has moved
    the marker to 200.0. A's write must be a no-op, not a resurrection of
    data computed against the pre-invalidation state."""
    from unittest.mock import MagicMock

    key = (93, "")
    fake_rdb = MagicMock()
    fake_rdb.list_ontology_types.return_value = []

    try:
        with patch.object(dtc, "_current_invalidation_marker", side_effect=[100.0, 200.0]), \
             patch.object(dtl, "get_cpq_rdb", return_value=fake_rdb):
            dtr._load_all_tables(93, "")
        assert key not in dtl._TABLES_CACHE, (
            "a write computed under the pre-invalidation marker must not "
            "repopulate the cache after a concurrent invalidation fired mid-compute"
        )
    finally:
        dtl._TABLES_CACHE.clear()
        dtl._TABLES_CACHE_LAST_SEEN_MARKER[0] = None


def test_load_all_tables_recomputes_after_marker_change_despite_valid_ttl():
    import time as _time
    from unittest.mock import MagicMock

    key = (93, "")
    dtl._TABLES_CACHE[key] = (_time.monotonic(), ("stale", "sentinel", "tuple", "here", "!"))
    dtl._TABLES_CACHE_LAST_SEEN_MARKER[0] = 100.0

    fake_rdb = MagicMock()
    fake_rdb.list_ontology_types.return_value = []

    try:
        with patch.object(dtc, "_current_invalidation_marker", return_value=200.0), \
             patch.object(dtl, "get_cpq_rdb", return_value=fake_rdb):
            dtr._load_all_tables(93, "")
        assert fake_rdb.list_ontology_types.called, (
            "the real fetch must run after a marker change, even though the "
            "seeded cache entry was still well within its own TTL"
        )
    finally:
        dtl._TABLES_CACHE.clear()
        dtl._TABLES_CACHE_LAST_SEEN_MARKER[0] = None
