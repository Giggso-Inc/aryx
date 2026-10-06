"""Cached lookup of function scripts reached through the CONTAINS link.

fetch_function_scripts runs from several places per Ask turn (hiding rules,
value rules, the BML evaluator, two NL-hint paths). On a workspace whose
scripts are not on the functions, every call would otherwise run two
queries returning every script body. The result is cached per
(workspace, catalog_prefix) and cleared when the catalog is re-ingested --
the same marker the data-table and attribute-search caches use -- with a
6 h TTL as a backstop. Only successful lookups are cached.
"""
from __future__ import annotations

import time
from typing import Any

from aryx.cpq.data_table import data_table_cache
from aryx.cpq.rdb.rdb_function_scripts import (
    SCRIPT_TEXT_SUFFIX,
    linked_scripts_by_function,
    mixed_text_entities,
)

_TTL_SECONDS = 6 * 3600.0
# (workspace_id, catalog_prefix) -> (cached_at, by_source, stats)
_CACHE: dict[tuple[int, str], tuple[float, dict[int, str], dict[str, int]]] = {}
_LAST_SEEN_MARKER: list[float | None] = [None]


def clear_linked_scripts_cache() -> None:
    """Drop every cached lookup (tests, or after a known re-ingest)."""
    _CACHE.clear()
    _LAST_SEEN_MARKER[0] = None


def linked_function_scripts(
    rdb: Any, workspace_id: int, catalog_prefix: str,
) -> tuple[dict[int, str], dict[str, int] | None]:
    """Function entity id -> script read through CONTAINS, plus lookup stats.

    Args:
        rdb: PostgresCpqRdb / OracleCpqRdb (fetch_contained_entities,
            fetch_member_payloads).
        workspace_id: Workspace being configured.
        catalog_prefix: Same prefix the functions were read with.

    Returns:
        (by_source, stats). stats is None on a cache hit (nothing new to
        report); otherwise it holds links, mixed_entities, skipped_links and
        verified (0 when the member check could not run, in which case
        by_source is empty and nothing is cached).
    """
    marker = data_table_cache._invalidate_on_marker_change(_CACHE, _LAST_SEEN_MARKER)
    key = (workspace_id, catalog_prefix)
    hit = _CACHE.get(key)
    if hit is not None and time.monotonic() - hit[0] < _TTL_SECONDS:
        return hit[1], None
    linked = rdb.fetch_contained_entities(workspace_id, SCRIPT_TEXT_SUFFIX, catalog_prefix)
    members = rdb.fetch_member_payloads(workspace_id, SCRIPT_TEXT_SUFFIX, catalog_prefix)
    if members is None:
        return {}, {"links": len(linked), "mixed_entities": 0, "skipped_links": 0, "verified": 0}
    mixed = mixed_text_entities(members)
    by_source, skipped = linked_scripts_by_function(linked, mixed)
    stats = {"links": len(linked), "mixed_entities": len(mixed), "skipped_links": skipped, "verified": 1}
    data_table_cache._cache_write_if_marker_unchanged(
        _CACHE, key, (time.monotonic(), by_source, stats), marker,
    )
    return by_source, stats
