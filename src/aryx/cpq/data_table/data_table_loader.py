"""Loads every ingested Data Table row for a workspace, classified by shape,
pooled across whatever tables were actually uploaded -- the single real
data-fetch path `cpq/data_table_resolver.py`'s resolver functions all sit on
top of.

Split out of `cpq/data_table_resolver.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03).
"""
from __future__ import annotations

import logging
import time
from typing import Any

from aryx.cpq.data_table.data_table_cache import (
    _cache_write_if_marker_unchanged,
    _invalidate_on_marker_change,
)
from aryx.cpq.data_table.data_table_shapes import _detect_shape
from aryx.cpq.rdb.rdb import get_cpq_rdb

logger = logging.getLogger(__name__)

_TABLES_CACHE_LAST_SEEN_MARKER: list[float | None] = [None]

# Module-level, short-TTL cache for _load_all_tables, keyed by (workspace_id,
# catalog_prefix). Mirrors engine.py's _LAYOUT_COMPONENTS_CACHE pattern.
# Needed because ask_api.py calls evaluate_rules_loop (and therefore
# _load_all_tables) multiple times per single /ask HTTP request, each with
# its own fresh per-call `cache` dict -- confirmed live against workspace 43
# (56,357 constraint rows, 46,865 sequence rows): 6+ consecutive full-table
# rescans (14-27s each) for the identical key within one turn. A short TTL
# (rather than pure process-lifetime) keeps this safe against a Data Table
# CSV being re-ingested mid-session.
_TABLES_CACHE: dict[tuple[int, str], tuple[float, tuple]] = {}
# docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md -- widened from 30.0.
# Live-measured: this cache almost never survived to the NEXT conversational
# turn (a customer reading a question and typing a reply routinely exceeds
# 30s), so nearly every real turn paid the full fresh-scan cost (up to 32.6s
# observed) a second time. The staleness risk this TTL exists for -- a Data
# Table CSV re-ingested mid-session -- is an occasional admin action, not a
# every-30-seconds occurrence; 300s gives real cross-turn hits while still
# bounding worst-case staleness to 5 minutes if the invalidation hook
# (doc_discovery.ingest_confirmed) is ever bypassed.
_TABLES_CACHE_TTL_SECONDS = 300.0


def _clear_tables_cache() -> None:
    """Test-isolation hook -- call from an autouse fixture to prevent this
    process-lifetime cache from leaking fake/monkeypatched rows between
    tests that reuse the same (workspace_id, catalog_prefix) key."""
    _TABLES_CACHE.clear()


def _load_all_tables(
    workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Query aryx_entity for every ingested entity type in this workspace,
    classify EVERY ROW by shape individually, and return
    (constraint_rows, sequence_rows, hierarchy_rows, series_mapping_rows,
    region_rule_rows) -- flat lists of {column: value} dicts pooled across
    every matching
    ingested table, whatever it's called.

    Two live-discovered bugs fixed here (confirmed against a real 453K-
    entity workspace with 72 ingested types):

    1. Fetches by EXACT ontology_type (fetch_entities_by_exact_type), not
       the LIKE-suffix fetch_entities_by_type. Two real ingested types can
       share a suffix -- "Whitelist" and "Advancedwhitelist" both end in
       "whitelist" -- so the suffix match for one silently pulled in the
       other's differently-shaped rows too, corrupting the pool.
    2. Classifies EACH ROW's shape independently, not the whole type from
       a single sample row. Real CSV rows can be sparse -- a row whose
       "Product" cell was empty in the source has no "Product" key stored
       at all -- so checking only entities[0] risks misclassifying (and
       silently dropping) an entire otherwise-valid type whenever its
       first-returned row (Postgres gives no ordering guarantee) happens
       to be a sparse or differently-shaped outlier. Confirmed live: a
       3,138-row CPQModelHierarchy-shaped type was entirely skipped this
       way because one row lacked "Product".

    catalog_prefix is accepted for interface consistency with the rest of
    the CPQ engine's workspace-scoping convention, but doesn't affect
    exact-type lookups here -- CSV-derived ontology_types never carry a
    catalog_prefix the way XML-derived rule/attr types do (see
    aryx.pipeline.doc_discovery.doc_discovery._stem_type), so there is nothing for it to
    filter on for Data Tables specifically.

    `cache`, when passed, is a plain dict the CALLER owns (typically for the
    lifetime of one auto_fill/evaluate_rules_loop pass) -- this function
    reuses a prior scan for the same (workspace_id, catalog_prefix) instead
    of re-querying, and also populates it from the module-level cache below
    when possible. Without it (default), the module-level cache is still
    consulted first.

    Beneath the per-call `cache`, a MODULE-LEVEL short-TTL cache
    (`_TABLES_CACHE`) also keys on (workspace_id, catalog_prefix) and
    survives across separate top-level calls -- confirmed live against a
    453K-entity, 72-ingested-type workspace: a single /ask HTTP request
    calls evaluate_rules_loop (and therefore this function) roughly 8 times,
    each with its own fresh per-call `cache` dict, so the per-call cache
    alone still repeated the full ~15-27s scan every time within one turn.
    The module-level cache collapses that to one scan per TTL window
    regardless of how many separate per-call caches are in play.
    """
    if cache is not None:
        key = (workspace_id, catalog_prefix)
        if key in cache:
            logger.info("cpq_perf: _load_all_tables CACHE HIT (call-local) ws=%s prefix=%r", workspace_id, catalog_prefix)
            return cache[key]

    _marker_at_read = _invalidate_on_marker_change(_TABLES_CACHE, _TABLES_CACHE_LAST_SEEN_MARKER)
    _mod_key = (workspace_id, catalog_prefix)
    _mod_hit = _TABLES_CACHE.get(_mod_key)
    if _mod_hit is not None:
        _mod_ts, _mod_result = _mod_hit
        if time.monotonic() - _mod_ts < _TABLES_CACHE_TTL_SECONDS:
            logger.info("cpq_perf: _load_all_tables CACHE HIT (module) ws=%s prefix=%r", workspace_id, catalog_prefix)
            if cache is not None:
                cache[_mod_key] = _mod_result
            return _mod_result

    _t0 = time.monotonic()
    rdb = get_cpq_rdb()
    constraint_rows: list[dict[str, Any]] = []
    sequence_rows: list[dict[str, Any]] = []
    hierarchy_rows: list[dict[str, Any]] = []
    series_mapping_rows: list[dict[str, Any]] = []
    region_rule_rows: list[dict[str, Any]] = []
    _bucket = {
        "constraint": constraint_rows,
        "sequence": sequence_rows,
        "hierarchy": hierarchy_rows,
        "series_mapping": series_mapping_rows,
        "region_rule": region_rule_rows,
    }

    # CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T2/data-table-resolution
    # follow-up (real-data testing against workspace 704, 2026-09-25): was
    # list_ontology_types() + one fetch_entities_by_exact_type() round trip
    # PER type (109 types here) -- confirmed live, ~411s for a single
    # resolve_region_allow_value() call. One grouped query instead.
    for ontology_type, entities in rdb.fetch_all_entities_grouped_by_type(workspace_id).items():
        if not entities:
            continue
        counts = {"constraint": 0, "sequence": 0, "hierarchy": 0, "series_mapping": 0, "region_rule": 0, None: 0}
        for _eid, attrs in entities:
            shape = _detect_shape(set(attrs.keys()))
            counts[shape] += 1
            if shape is not None:
                _bucket[shape].append(attrs)
        logger.debug(
            "data_table_resolver: %s (%d rows) -- constraint=%d sequence=%d "
            "hierarchy=%d series_mapping=%d region_rule=%d unrecognized=%d",
            ontology_type, len(entities), counts["constraint"],
            counts["sequence"], counts["hierarchy"], counts["series_mapping"],
            counts["region_rule"], counts[None],
        )

    result = (constraint_rows, sequence_rows, hierarchy_rows, series_mapping_rows, region_rule_rows)
    logger.info(
        "cpq_perf: _load_all_tables MISS (fresh scan) took %.3fs ws=%s prefix=%r "
        "constraint=%d sequence=%d hierarchy=%d series_mapping=%d region_rule=%d",
        time.monotonic() - _t0, workspace_id, catalog_prefix,
        len(constraint_rows), len(sequence_rows), len(hierarchy_rows),
        len(series_mapping_rows), len(region_rule_rows),
    )
    if cache is not None:
        cache[(workspace_id, catalog_prefix)] = result
    _cache_write_if_marker_unchanged(_TABLES_CACHE, _mod_key, (time.monotonic(), result), _marker_at_read)
    return result
