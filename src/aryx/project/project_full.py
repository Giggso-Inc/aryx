"""Full knowledge-graph rebuild from the RDB (stage 5d).

Split out of `aryx.project` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
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
    graph: "FalkorStore",
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
            rows, on_batch=lambda done: _scaled(done, n_entities_total, "entities"),
            full_rebuild=True)
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
        n_relationships = graph.add_relationships_batch(
            all_rels, full_rebuild=True) or len(all_rels)
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
