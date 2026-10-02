"""Deterministic cross-table dimension-hub linking (Tier 2).

Deterministic FK detection (dynamic_fk.py) and the LLM cross-type relate
passes (enrich.py) both answer one narrow question: does a SPECIFIC row in
one table point at a SPECIFIC row in another? A table with no row-level key
— every column is a repeated category, not a unique identifier — correctly
fails both, even when it shares an obvious real-world dimension (state,
fiscal period, federal supply class) with other ingested tables. That
dimension overlap is exactly what dynamic_fk.py already measures and
REJECTS for FK purposes, because a low-cardinality shared column is a bad
join key (it would create a combinatorial explosion of row-to-row edges).

This module makes the opposite use of the same signal: instead of a hard
FK edge between two specific rows, it creates ONE small hub entity per
distinct shared dimension value (e.g. one node for "State=PA") and links
every entity — across every type — whose row carries that value to the hub.
This is a real incident fix: a 300K-row disposition report had no usable
row-level key and stayed 100% isolated across the graph, even though its
"State" and "FSC Group" columns had 100% value overlap with other ingested
tables (confirmed via dynamic_fk's own logged, correctly-rejected FK
candidates) — a real, if coarse, connection the pipeline had no way to
represent. See docs/design/keyless_table_linking.md for the full design.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`dimension_link_columns.py` (candidate-column extraction/filtering) and
`dimension_link_groups.py` (union-find clustering), both re-imported
here. Neither calls `get_settings()` nor is itself patched — the one
patch on this module (`aryx.pipeline.dimension_link.dimension_link.get_settings`, from
`tests/test_dimension_link.py`) is called only inside
`detect_and_link_dimensions`, which stays here.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable

from aryx.config import get_settings
from aryx.models import Relationship
from aryx.pipeline.dimension_link.dimension_link_columns import (
    CandidateKey,
    ValueMap,
    _candidate_columns,
    _is_dimension_column,
)
from aryx.pipeline.dimension_link.dimension_link_groups import _dimension_groups
from aryx.pipeline.value_normalize import normalize_value
from aryx.store.entity_store import EntityStore

__all__ = [
    "CandidateKey",
    "ValueMap",
    "detect_and_link_dimensions",
]

logger = logging.getLogger(__name__)


def detect_and_link_dimensions(
    estore: EntityStore, should_stop: Callable[[], bool] | None = None,
) -> int:
    """Connect entities across types that share a low-cardinality dimension
    column, with no row-level key required. Deliberately a WEAKER, distinctly
    named edge (has_<dimension>, confidence 0.5) than a real FK or an
    LLM-confirmed relationship — it claims shared context, not identity.

    Self-contained (queries current entities itself) and a safe no-op when
    nothing qualifies. Intended to run once, after all other linking passes,
    right before graph projection.

    should_stop — optional, checked at the top of both the per-group and
    per-value loops below. This is the actual stage that ran away for 20+
    minutes after a job was "cancelled" (the cancel endpoint only updated a
    job-store row; nothing here ever read it back) — a wide reference table
    with many distinct attr/val pairs can produce thousands of dimension
    hub entities, one create_entity() call at a time, with no other natural
    exit point. should_stop() itself is cheap (throttled to at most one real
    check per second, see file_ingest_api.make_should_stop), so checking it
    every inner iteration is safe.
    """
    cfg = get_settings()
    if not cfg.dimension_link_enabled:
        return 0

    entities = list(estore.list_entities())
    if not entities:
        return 0

    by_type_col_val = _candidate_columns(entities)
    rows_per_type: dict[str, int] = defaultdict(int)
    for _eid, etype, _attrs in entities:
        rows_per_type[etype] += 1

    candidates: dict[CandidateKey, ValueMap] = {}
    for etype, cols in by_type_col_val.items():
        total = rows_per_type[etype]
        for col, value_map in cols.items():
            if _is_dimension_column(
                value_map, total,
                cfg.dimension_min_distinct_values, cfg.dimension_max_cardinality_ratio,
            ):
                candidates[(etype, col)] = value_map

    if len(candidates) < 2:
        logger.debug("dimension_link: fewer than 2 dimension candidate columns — skipping")
        return 0

    dimension_groups = _dimension_groups(
        candidates, cfg.dimension_min_overlap, cfg.dimension_min_types,
    )
    if not dimension_groups:
        logger.info("dimension_link: no cross-type dimension groups found")
        return 0

    max_rels = cfg.dimension_max_edges_per_group
    total_edges = 0
    stopped = False
    for group_idx, group in enumerate(dimension_groups):
        if should_stop is not None and should_stop():
            stopped = True
            logger.warning(
                "dimension_link: job cancelled — stopping after %d/%d groups, "
                "%d edges linked so far", group_idx, len(dimension_groups), total_edges,
            )
            break
        name_counts: dict[str, int] = defaultdict(int)
        for _etype, col in group:
            name_counts[col] += 1
        canonical_col = max(name_counts, key=name_counts.get)
        dim_name = normalize_value(canonical_col).replace(" ", "_") or "dimension"

        value_hub_ids: dict[str, int] = {}
        rels: list[Relationship] = []
        capped = False
        for etype, col in group:
            if capped:
                break
            for value, ids in candidates[(etype, col)].items():
                if should_stop is not None and should_stop():
                    stopped = True
                    capped = True  # reuse the same "save partial, stop this group" path below
                    break
                hub_id = value_hub_ids.get(value)
                if hub_id is None:
                    hub_id = estore.create_entity(
                        f"Dimension:{dim_name.title()}",
                        {"value": value, "_dimension": dim_name},
                        confidence=0.5,
                    )
                    value_hub_ids[value] = hub_id
                for eid in ids:
                    rels.append(Relationship(
                        source_entity_id=eid, target_entity_id=hub_id,
                        name=f"has_{dim_name}", confidence=0.5,
                    ))
                    if len(rels) >= max_rels:
                        capped = True
                        break
                if capped:
                    break
        if capped:
            # Weak/best-effort linking, unlike hard FK detection: save the
            # partial edges collected so far instead of aborting the group.
            logger.warning(
                "dimension_link: dimension=%s exceeded dimension_max_edges_per_group=%d "
                "— saving %d edges collected so far, not aborting",
                dim_name, max_rels, len(rels),
            )
        if rels:
            estore.save_relationships(rels)
            total_edges += len(rels)
            logger.info(
                "dimension_link: dimension=%s types=%s hub_entities=%d edges=%d",
                dim_name, sorted({t for t, _ in group}), len(value_hub_ids), len(rels),
            )
        if stopped:
            # Cancelled mid-group: the partial edges collected up to the
            # cancellation point were just saved above (same "save what we
            # have, don't discard it" contract as the max_rels cap) — now
            # actually stop, rather than continuing on to the next group.
            break
    return total_edges
