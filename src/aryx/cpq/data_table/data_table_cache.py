"""Cross-process cache-invalidation primitives shared by every module-level
cache in the CPQ engine (`cpq/data_table_resolver.py`'s own table cache,
plus `cpq/engine.py`'s `_RULE_JOIN_DATA_CACHE`/`_VALUE_RULES_CACHE` and its
other in-memory caches).

Split out of `cpq/data_table_resolver.py` (Raven Style Compliance Plan,
Phase 2, 2026-09-03) into its own dependency-free module specifically so
`cpq/engine.py` can import these primitives without creating a circular
import -- `data_table_resolver.py` already imports FROM `engine.py`'s
sibling modules in the other direction, so this generic infrastructure
cannot live in either of the two files that need to share it without one
importing the other.
"""
from __future__ import annotations

import logging
import time

from aryx.config import get_settings

logger = logging.getLogger(__name__)

# 2026-08-29 (PR #287 review, Section 12 of the concurrency-delay report):
# under a single api worker process, ingest_confirmed's plain
# cache.clear() calls were sufficient to keep this and engine.py's 4
# sibling 300s-TTL caches safe against a mid-session re-ingest. P1
# (multi-worker uvicorn, same PR) breaks that assumption: a re-ingest
# handled by one worker process never reaches another worker's
# independent copy of the same in-memory cache.
#
# Fix: cpq_cache_invalidation_marker (migration 0040) is a single-row
# Postgres table every worker can see.
_INVALIDATION_MARKER_POLL_SECONDS = 7.0
_INVALIDATION_MARKER_FAIL_RETRY_SECONDS = 2.0
_INVALIDATION_MARKER_POLL_CACHE: tuple[float, float | None] | None = None


def _fetch_invalidation_marker_from_db() -> float | None:
    """One tiny SELECT against the shared marker table. Returns a UNIX
    epoch float, or None if the table/row doesn't exist, the query
    failed, or the result wasn't actually numeric -- callers treat None
    as "can't verify right now," never as "no invalidation happened," so
    a transient failure can only ever widen the staleness window back
    toward the pre-fix TTL-only behavior, not silently hide real state.

    The isinstance check below is not defensive-programming theater --
    confirmed live (2026-08-29): a test-environment-only global mock of
    psycopg_pool.ConnectionPool (an unrelated file's own sys.modules.
    setdefault, tests/test_pool.py) can make the whole connection/cursor
    chain above "succeed" against a fake pool instead of raising, so
    row[0].timestamp() can return a MagicMock instead of a float without
    ever hitting the except clause below. Comparing two of those in
    _invalidate_on_marker_change then raises an uncaught TypeError --
    validating the type here, at the one place real data enters this
    module, keeps every caller correctly fail-open against ANY
    unexpected result shape, not just a raised exception.
    """
    try:
        from aryx.store.pool import get_pool

        # Explicit short acquisition timeout -- this is a background poll
        # check, not a real request the customer is waiting on. psycopg_
        # pool's own default connection() timeout is 30s.
        with get_pool(get_settings().effective_dsn()).connection(timeout=1.0) as conn, conn.cursor() as cur:
            cur.execute("SELECT invalidated_at FROM cpq_cache_invalidation_marker WHERE id = 1")
            row = cur.fetchone()
        if row is None or row[0] is None:
            return None
        marker_ts = row[0].timestamp()
        if not isinstance(marker_ts, (int, float)):
            logger.debug(
                "cpq: invalidation marker fetch returned a non-numeric "
                "value (%r) -- treating as unavailable", type(marker_ts),
            )
            return None
        return marker_ts
    except Exception:
        logger.debug("cpq: invalidation marker fetch failed", exc_info=True)
        return None


def _current_invalidation_marker() -> float | None:
    """Cross-process invalidation marker, polled at most once per
    _INVALIDATION_MARKER_POLL_SECONDS per process."""
    global _INVALIDATION_MARKER_POLL_CACHE
    now = time.monotonic()
    if _INVALIDATION_MARKER_POLL_CACHE is not None:
        checked_at, marker_ts = _INVALIDATION_MARKER_POLL_CACHE
        if now - checked_at < _INVALIDATION_MARKER_POLL_SECONDS:
            return marker_ts
    marker_ts = _fetch_invalidation_marker_from_db()
    next_checked_at = now if marker_ts is not None else (
        now - _INVALIDATION_MARKER_POLL_SECONDS + _INVALIDATION_MARKER_FAIL_RETRY_SECONDS
    )
    _INVALIDATION_MARKER_POLL_CACHE = (next_checked_at, marker_ts)
    return marker_ts


def _clear_invalidation_marker_poll_cache() -> None:
    """Test-isolation hook -- mirrors the other _clear_*_cache helpers."""
    global _INVALIDATION_MARKER_POLL_CACHE
    _INVALIDATION_MARKER_POLL_CACHE = None


def _invalidate_on_marker_change(
    cache_dict: dict, last_seen_holder: list[float | None],
) -> float | None:
    """Blanket-clears `cache_dict` the first time this process observes a
    NEWER marker than the last one it accounted for. `last_seen_holder`
    is a single-element list so each of this codebase's caches can
    share this one function with its own independent "last seen" state.

    Returns the marker_ts observed by this call (or None if unavailable) --
    callers pass this to `_cache_write_if_marker_unchanged` so a write that
    started before a concurrent invalidation doesn't repopulate the cache
    with a value computed against the stale, pre-invalidation state. Needed
    because `_dispatch` (and everything it calls, including these caches)
    now runs on a real thread pool via asyncio.to_thread rather than inline
    on the single event-loop thread -- concurrent MCP tool calls can
    genuinely interleave here for the first time.
    """
    marker_ts = _current_invalidation_marker()
    if marker_ts is None:
        return None
    if last_seen_holder[0] is None:
        last_seen_holder[0] = marker_ts
        return marker_ts
    # The fail-open contract this mechanism promises must hold even if
    # _current_invalidation_marker's own type validation is ever bypassed
    # -- a comparison TypeError here must degrade to "skip this check,"
    # never propagate and crash the real cache read it only gates.
    try:
        is_newer = marker_ts > last_seen_holder[0]
    except TypeError:
        logger.debug(
            "cpq: invalidation marker comparison failed (marker_ts=%r, "
            "last_seen=%r) -- skipping this check",
            marker_ts, last_seen_holder[0],
        )
        return marker_ts
    if is_newer:
        cache_dict.clear()
        last_seen_holder[0] = marker_ts
    return marker_ts


def _cache_write_if_marker_unchanged(
    cache_dict: dict, key: object, value: object, marker_ts_at_read: float | None,
) -> None:
    """Guarded write-back for module-level caches gated by
    `_invalidate_on_marker_change`. Re-checks the invalidation marker
    hasn't advanced since `marker_ts_at_read` was captured (right after
    the read-time invalidation check, before the possibly-slow compute
    that produced `value`); if it has, another thread cleared this cache
    for a real reason while this thread was still computing against the
    old state, and writing `value` back now would silently resurrect
    stale data under a fresh timestamp. Skipping the write just costs a
    cache miss next read -- never incorrect data."""
    if _current_invalidation_marker() != marker_ts_at_read:
        logger.debug("cpq: skipping stale cache write for key=%r -- marker advanced mid-compute", key)
        return
    cache_dict[key] = value
