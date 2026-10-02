"""Translate raw graph CONTAINS edges into curated-graph Relationship rows.

Every other relate stage (`_detect_fk_links`, `dynamic_fk`, schema_fk,
`_relate`) exists to *guess* which entities are connected, because a CSV row
carries no structural information beyond its own columns. A raw graph
already knows the true parent/child structure from the XML itself --
``RawEdge(source_id, target_id, "CONTAINS")`` -- so none of that guessing is
needed for these edges: once both endpoints have been resolved into
entities, the edge translates directly.

Deliberately just the translation, not the lookup: building the
``node_id -> entity_id`` mapping needs a live resolve run's ``run_id`` and a
join through ``aryx_landed_record``/``aryx_entity_member`` (only meaningful
once resolve has actually executed against Postgres), which belongs in the
orchestration piece that calls this, not here -- keeps this piece a pure,
DB-free function, testable the same way ``resolve_adapter.py`` and
``match_key_inference.py`` are.
"""
from __future__ import annotations

import logging

from aryx.cpq_ingestion.raw_graph.models import RawEdge
from aryx.models import Relationship

logger = logging.getLogger(__name__)


def translate_containment_edges(
    edges: list[RawEdge],
    node_id_to_entity_id: dict[int, int],
    *,
    confidence: float = 1.0,
    log_id: str | None = None,
) -> list[Relationship]:
    """Map each CONTAINS edge onto its resolved entities, where both resolved.

    An edge is silently skipped (and counted, once, in a summary warning --
    not logged per edge, which could be thousands) when either endpoint's
    node was never resolved into an entity. This happens legitimately: a
    node whose tag never became an ontology_type (e.g. a leaf/container
    element that wasn't run through resolve at all) has no entry in the
    mapping. Losing that one edge is the same "best-effort provenance,
    never blocks ingestion" posture already applied to the raw graph write
    itself (see ``pipeline.py``'s ``project_raw_graph_and_flatten``).

    Two or more raw edges can collapse onto the same resolved entity pair
    when resolve merges distinct raw nodes into one entity (e.g. duplicate
    Customer elements) -- the result is deduplicated on
    ``(source_entity_id, target_entity_id, name)``, keeping the first
    occurrence's confidence, so the curated graph gets one edge, not N
    identical ones.
    """
    seen: set[tuple[int, int, str]] = set()
    relationships: list[Relationship] = []
    skipped = 0

    for edge in edges:
        source_eid = node_id_to_entity_id.get(edge.source_id)
        target_eid = node_id_to_entity_id.get(edge.target_id)
        if source_eid is None or target_eid is None:
            skipped += 1
            continue
        dedup_key = (source_eid, target_eid, edge.name)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        relationships.append(Relationship(
            source_entity_id=source_eid, target_entity_id=target_eid,
            name=edge.name, confidence=confidence,
        ))

    if skipped:
        logger.warning(
            "raw_graph containment_relate did=%s edges_total=%d skipped_unresolved_endpoint=%d",
            log_id, len(edges), skipped,
        )
    logger.info(
        "raw_graph containment_relate did=%s edges_total=%d relationships_written=%d",
        log_id, len(edges), len(relationships),
    )
    return relationships
