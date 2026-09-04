"""Incremental knowledge-graph update from the Postgres dirty set (G8).

Split out of `aryx.project` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aryx.graph import FalkorStore

from aryx.project_full import _entity_iri
from aryx.store.entity_store import EntityStore

logger = logging.getLogger(__name__)


def project_incremental(
    store: "EntityStore",
    pstore,
    graph: "FalkorStore",
    type_ancestors: dict[str, list[str]] | None = None,
    workspace_id: int | None = None,
    base_uri: str = "https://aryx.local/",
) -> dict[str, int]:
    """Update the graph in place from the Postgres dirty set (G8).

    Never calls ``clear()`` — the graph stays queryable throughout. Upserts
    dirty entities (MERGE is idempotent), re-MERGEs their provenance and
    relationship edges, DETACH-DELETEs tombstones, advances the watermark.
    ``pstore`` is a ProjectionStore; other args match ``project_graph``.

    Entities and provenance are written via the same batched UNWIND path
    ``project_graph`` already uses for a full import (docs/
    falkordb_high_cpu_2026-07-29.md, ingestion bottleneck A) — this
    function previously issued one MERGE round-trip per dirty entity and
    per provenance row even though the batch writers were measured ~8x
    faster, and this is the MORE frequently exercised path (routine
    dirty-set updates run far more often than a full re-import), so the
    gap mattered more here, not less. Relationship writes already used
    the batch path; only entities/provenance needed this.

    Returns:
        Counts of {entities, provenance, relationships, tombstones} written.
    """
    since = pstore.watermark()
    ancestors_for = type_ancestors or {}
    dirty = pstore.dirty_entities(since)
    if hasattr(graph, "add_entities_batch"):
        rows = [
            (eid, ot, attrs, ancestors_for.get(ot, []),
             _entity_iri(base_uri, workspace_id, eid))
            for eid, ot, attrs in dirty
        ]
        graph.add_entities_batch(rows)
    else:
        for entity_id, ontology_type, attributes in dirty:
            labels = ancestors_for.get(ontology_type, [])
            iri = _entity_iri(base_uri, workspace_id, entity_id)
            graph.add_entity(entity_id, ontology_type, attributes,
                             labels=labels, iri=iri)
    dirty_ids = [e[0] for e in dirty]
    provenance = pstore.provenance_for(dirty_ids) if dirty_ids else []
    if hasattr(graph, "add_provenance_batch"):
        graph.add_provenance_batch(provenance)
    else:
        for entity_id, system, dataset, record_id in provenance:
            graph.add_provenance(entity_id, system, dataset, record_id)
    relationships = pstore.relationships_for(dirty_ids) if dirty_ids else []
    if hasattr(graph, "add_relationships_batch"):
        graph.add_relationships_batch(relationships)
    else:
        for src, tgt, name in relationships:
            graph.add_relationship(src, tgt, name)
    tombstones = pstore.tombstones()
    # Captured *before* DETACH DELETE below — a tombstone's neighbor can
    # become newly isolated once its only edge is gone, and that neighbor
    # is otherwise outside this batch's own dirty set (Raven review, PR
    # #147 finding #2: mark_isolated_entities() must not re-scan the whole
    # graph on every small incremental update).
    tombstone_neighbor_ids = (
        graph.neighbor_ids(tombstones)
        if tombstones and hasattr(graph, "neighbor_ids") else []
    )
    for entity_id in tombstones:
        graph.remove_entity(entity_id)
    if hasattr(graph, "mark_isolated_entities"):
        rel_endpoint_ids = {eid for src, tgt, _ in relationships for eid in (src, tgt)}
        scope_ids = sorted(set(dirty_ids) | rel_endpoint_ids | set(tombstone_neighbor_ids))
        graph.mark_isolated_entities(entity_ids=scope_ids)
    if hasattr(graph, "ensure_indexes"):
        graph.ensure_indexes()
    pstore.mark_projected(dirty_ids)
    pstore.unmark_projected(tombstones)
    pstore.advance_watermark()
    counts = {"entities": len(dirty), "provenance": len(provenance),
              "relationships": len(relationships),
              "tombstones": len(tombstones)}
    logger.info("graph incrementally projected %s", counts)
    return counts
