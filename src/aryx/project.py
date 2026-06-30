"""Knowledge-graph projection orchestration (stage 5d): RDB -> FalkorDB."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aryx.graph import FalkorStore

from aryx.store.entity_store import EntityStore

logger = logging.getLogger(__name__)


def _entity_iri(base_uri: str, workspace_id: int | None, entity_id: int) -> str:
    """Mint the stable IRI for an entity.

    Deterministic from ``(workspace_id, entity_id)``; ``entity_id`` is a
    BIGSERIAL that is never reused, so the IRI is frozen for life.
    """
    base = base_uri if base_uri.endswith("/") else base_uri + "/"
    ws = workspace_id if workspace_id is not None else 0
    return f"{base}entity/{ws}/{entity_id}"


def project_graph(
    store: EntityStore,
    graph: FalkorStore,
    type_ancestors: dict[str, list[str]] | None = None,
    workspace_id: int | None = None,
    base_uri: str = "https://aryx.local/",
) -> dict[str, int]:
    """Rebuild the FalkorDB graph from the RDB (the source of truth).

    Wipes the graph, then writes entity nodes (with ancestor labels and a
    stable IRI when available), provenance edges, and relationship edges.
    Always safe to re-run.

    Args:
        store: Open entity store (reads from Postgres).
        graph: Open FalkorDB writer.
        type_ancestors: Optional ``{type_name: [parent, grandparent, ...]}``
            map. When supplied, ancestors are attached as additional Cypher
            labels (rdfs:subClassOf at the graph layer). When None, behavior
            matches the pre-hierarchy projection.
        workspace_id: Workspace this projection belongs to; folded into the
            entity IRI when present.
        base_uri: URI prefix for minted entity IRIs. Defaults to the local
            placeholder used in tests and ``ontology/rdf`` export.

    Returns:
        Counts of {entities, provenance, relationships} written.
    """
    logger.info("graph project start ws=%s — clearing", workspace_id)
    graph.clear()
    logger.info("graph cleared — writing entities")

    ancestors_for = type_ancestors or {}

    if hasattr(graph, "add_entities_batch"):
        # Oracle batch path: collect all rows, then write in 3 round-trips per phase
        logger.info("graph collecting entities from store...")
        entity_rows = [
            (eid, typ, attrs, ancestors_for.get(typ, []), _entity_iri(base_uri, workspace_id, eid))
            for eid, typ, attrs in store.list_entities()
        ]
        n_entities = len(entity_rows)
        logger.info("graph entities collected %d — batch inserting vertices", n_entities)
        graph.add_entities_batch(entity_rows)
        logger.info("graph entities done total=%d — collecting provenance links", n_entities)

        logger.info("graph collecting provenance links from store...")
        prov_rows = list(store.list_members_provenance())
        n_provenance = len(prov_rows)
        logger.info("graph provenance collected %d — batch inserting provenance", n_provenance)
        graph.add_provenance_batch(prov_rows)
        logger.info("graph provenance done total=%d — collecting relationships", n_provenance)

        logger.info("graph collecting relationships from store...")
        rel_rows = list(store.list_relationships())
        n_relationships = len(rel_rows)
        logger.info("graph relationships collected %d — batch inserting edges", n_relationships)
        graph.add_relationships_batch(rel_rows)
        logger.info("graph relationships done total=%d", n_relationships)
    else:
        # FalkorStore / Postgres path: per-item loop with progress logs
        n_entities = 0
        for entity_id, ontology_type, attributes in store.list_entities():
            labels = ancestors_for.get(ontology_type, [])
            iri = _entity_iri(base_uri, workspace_id, entity_id)
            graph.add_entity(entity_id, ontology_type, attributes,
                             labels=labels, iri=iri)
            n_entities += 1
            if n_entities % 50 == 0:
                logger.info("graph entities written %d", n_entities)
        logger.info("graph entities done total=%d — writing provenance", n_entities)

        n_provenance = 0
        for entity_id, system, dataset, record_id in store.list_members_provenance():
            graph.add_provenance(entity_id, system, dataset, record_id)
            n_provenance += 1
            if n_provenance % 100 == 0:
                logger.info("graph provenance written %d", n_provenance)
        logger.info("graph provenance done total=%d — writing relationships", n_provenance)

        n_relationships = 0
        for source_id, target_id, name in store.list_relationships():
            graph.add_relationship(source_id, target_id, name)
            n_relationships += 1
        logger.info("graph relationships done total=%d", n_relationships)

    counts = {"entities": n_entities, "provenance": n_provenance,
              "relationships": n_relationships}
    logger.info("graph projected %s labels_used=%d",
                counts, sum(1 for v in ancestors_for.values() if v))
    return counts


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

    Returns:
        Counts of {entities, provenance, relationships, tombstones} written.
    """
    since = pstore.watermark()
    ancestors_for = type_ancestors or {}
    dirty = pstore.dirty_entities(since)
    for entity_id, ontology_type, attributes in dirty:
        labels = ancestors_for.get(ontology_type, [])
        iri = _entity_iri(base_uri, workspace_id, entity_id)
        graph.add_entity(entity_id, ontology_type, attributes,
                         labels=labels, iri=iri)
    dirty_ids = [e[0] for e in dirty]
    provenance = pstore.provenance_for(dirty_ids) if dirty_ids else []
    for entity_id, system, dataset, record_id in provenance:
        graph.add_provenance(entity_id, system, dataset, record_id)
    relationships = pstore.relationships_for(dirty_ids) if dirty_ids else []
    for source_id, target_id, name in relationships:
        graph.add_relationship(source_id, target_id, name)
    tombstones = pstore.tombstones()
    for entity_id in tombstones:
        graph.remove_entity(entity_id)
    pstore.mark_projected(dirty_ids)
    pstore.unmark_projected(tombstones)
    pstore.advance_watermark()
    counts = {"entities": len(dirty), "provenance": len(provenance),
              "relationships": len(relationships),
              "tombstones": len(tombstones)}
    logger.info("graph incrementally projected %s", counts)
    return counts


def project_auto(
    store: "EntityStore",
    pstore,
    graph: "FalkorStore",
    dirty_ratio_max: float = 0.30,
    **kwargs,
) -> dict[str, int]:
    """Pick incremental vs full rebuild (G8 mode=auto).

    Incremental when a watermark exists AND the dirty set is under
    ``dirty_ratio_max`` (env ARYX_PROJECT_DIRTY_MAX overrides) of all
    entities; full rebuild otherwise — it remains the correctness anchor.
    """
    import os
    try:
        dirty_ratio_max = float(os.environ.get("ARYX_PROJECT_DIRTY_MAX",
                                               dirty_ratio_max))
    except ValueError:
        pass
    since = pstore.watermark()
    if since is not None:
        total = pstore.total_entities()
        dirty = len(pstore.dirty_entities(since))
        if total and dirty / total < dirty_ratio_max:
            return project_incremental(store, pstore, graph, **kwargs)
    counts = project_graph(store, graph, **kwargs)
    pstore.mark_projected([e[0] for e in store.list_entities()])
    pstore.advance_watermark()
    return counts
