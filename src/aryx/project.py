"""Knowledge-graph projection orchestration (stage 5d): RDB -> FalkorDB."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aryx.graph import FalkorStore

from aryx.store.entity_store import EntityStore

logger = logging.getLogger(__name__)

# (stage_label, pct) -> row-count callback contract used by orchestrate.py's
# on_progress (see docs/CPQ_INGESTION_PROJECTION_PERFORMANCE_PLAN.md §6.4):
# the Project stage previously reported ONE point at entry (90) and one at
# exit (95/100) no matter how long it took, which is what let an external
# timeout watchdog mark a genuinely-still-working job "failed" mid-run
# (confirmed live). ProjectProgress scales smoothly across that window by
# actual rows written instead.
ProjectProgress = Callable[[str, int, str], None]


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
    on_progress: ProjectProgress | None = None,
    pct_range: tuple[int, int] = (90, 95),
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
        on_progress: Optional (stage, pct, detail) callback — see
            docs/CPQ_INGESTION_PROJECTION_PERFORMANCE_PLAN.md §6.4. Called
            with real row-write progress scaled across pct_range instead of
            once at entry and once at exit, so a slow run stays visibly
            alive instead of looking hung to any external timeout watchdog.
        pct_range: (start, end) percentage window this stage reports into —
            matches orchestrate.py's existing "Project" 90->95 milestones.

    Returns:
        Counts of {entities, provenance, relationships} written.
    """
    logger.info("graph project start ws=%s — clearing", workspace_id)
    graph.clear()
    logger.info("graph cleared — writing entities")
    ancestors_for = type_ancestors or {}
    lo, hi = pct_range
    span = max(hi - lo, 1)

    def _scaled(done: int, total: int, phase: str) -> None:
        if on_progress is None or not total:
            return
        pct = lo + int(span * min(done, total) / total)
        on_progress("Project", pct, f"{phase}: {done}/{total}")

    entities = list(store.list_entities())
    n_entities_total = len(entities)
    if hasattr(graph, "add_entities_batch"):
        rows = [
            (eid, ot, attrs, ancestors_for.get(ot, []),
             _entity_iri(base_uri, workspace_id, eid))
            for eid, ot, attrs in entities
        ]
        n_entities = graph.add_entities_batch(
            rows, on_batch=lambda done: _scaled(done, n_entities_total, "entities"))
    else:
        n_entities = 0
        for entity_id, ontology_type, attributes in entities:
            labels = ancestors_for.get(ontology_type, [])
            iri = _entity_iri(base_uri, workspace_id, entity_id)
            graph.add_entity(entity_id, ontology_type, attributes,
                             labels=labels, iri=iri)
            n_entities += 1
            _scaled(n_entities, n_entities_total, "entities")

    provenance = list(store.list_members_provenance())
    n_provenance_total = len(provenance)
    if hasattr(graph, "add_provenance_batch"):
        n_provenance = graph.add_provenance_batch(
            provenance,
            on_batch=lambda done: _scaled(done, n_provenance_total, "provenance"))
    else:
        n_provenance = 0
        for entity_id, system, dataset, record_id in provenance:
            graph.add_provenance(entity_id, system, dataset, record_id)
            n_provenance += 1
            _scaled(n_provenance, n_provenance_total, "provenance")

    all_rels = list(store.list_relationships())
    if hasattr(graph, "add_relationships_batch"):
        n_relationships = graph.add_relationships_batch(all_rels)
    else:
        for src, tgt, name in all_rels:
            graph.add_relationship(src, tgt, name)
        n_relationships = len(all_rels)
    _scaled(len(all_rels), len(all_rels) or 1, "relationships")

    if hasattr(graph, "mark_isolated_entities"):
        graph.mark_isolated_entities()
    if hasattr(graph, "ensure_indexes"):
        graph.ensure_indexes()

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
    for entity_id in tombstones:
        graph.remove_entity(entity_id)
    if hasattr(graph, "mark_isolated_entities"):
        graph.mark_isolated_entities()
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
