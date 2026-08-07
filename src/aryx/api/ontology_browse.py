"""Browse helper for the ontology API — types, attrs, relationship counts.

Workspace-scoped: every entry-point takes the workspace_id and threads it
through the OntologyStore so DEMO's types never appear in Default and
vice-versa.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.config import get_settings
from aryx.store.entity_store import EntityStore
from aryx.store.ontology_store import OntologyStore

logger = logging.getLogger(__name__)


def approve(name: str, workspace_id: int = 1) -> dict[str, Any]:
    """Approve a proposed ontology type via the HITL gate."""
    store = OntologyStore(get_settings().rdb_dsn, workspace_id)
    try:
        store.approve_type(name)
    finally:
        store.close()
    return {"status": "approved", "name": name}


def add_type(name: str, attributes: Any, status: str = "approved",
             source: str = "manual",
             workspace_id: int = 1) -> dict[str, Any]:
    """Manually create an ontology type. attributes: list[str] | dict[str,_]."""
    from aryx.models import OntologyType
    if isinstance(attributes, dict):
        attrs = [str(k) for k in attributes.keys()]
    elif isinstance(attributes, list):
        attrs = [str(x) for x in attributes]
    else:
        attrs = []
    store = OntologyStore(get_settings().rdb_dsn, workspace_id)
    try:
        store.seed_types([OntologyType(name=name, attributes=attrs,
                                       status=status, source=source)])
    finally:
        store.close()
    return {"status": "ok", "name": name}


def _implicit_types_from_entities(entities: list[dict[str, Any]],
                                  known_type_names: set[str]) -> list[Any]:
    """Type rows for entities whose type the schema pass didn't declare.

    Individuals can be typed only implicitly (rdf:type pointing at a bare
    URI, no owl:Class declaration anywhere) — those still deserve a type
    row so they show up in the Model/Lightweight views, not just the graph.
    """
    from aryx.models import OntologyType
    attrs_by_type: dict[str, set[str]] = {}
    for e in entities:
        if e["type"] in known_type_names:
            continue
        keys = {k for k in e["attributes"] if k != "_rdf_iri"}
        attrs_by_type.setdefault(e["type"], set()).update(keys)
    return [OntologyType(name=name, attributes=sorted(attrs),
                         status="proposed", source="owl-import")
            for name, attrs in attrs_by_type.items()]


def _ingest_instances(entities: list[dict[str, Any]], links: list[dict[str, str]],
                      workspace_id: int) -> tuple[int, int]:
    """Persist RDF individuals as real entities + the relationships between
    them, then re-project the graph.

    Bypasses the discover/resolve pipeline entirely — these individuals
    already carry stable, globally-unique identity (their IRI), so there's
    no fuzzy-matching/dedup step to run; each becomes exactly one entity.
    """
    if not entities:
        return 0, 0
    from aryx.graph import FalkorStore
    from aryx.models import Relationship, ResolvedEntity
    from aryx.pipeline.enrich import _build_type_ancestors
    from aryx.project import project_graph
    from aryx.workspaces import ws_graph

    settings = get_settings()
    estore = EntityStore(settings.rdb_dsn, workspace_id)
    try:
        to_save = [
            (ResolvedEntity(ontology_type=e["type"], attributes=e["attributes"],
                            confidence=1.0), [])
            for e in entities
        ]
        ids = estore.save_returning_ids(to_save)
        iri_to_id = {e["iri"]: eid for e, eid in zip(entities, ids)}
        rels: list[Relationship] = []
        skipped = 0
        for link in links:
            source_id = iri_to_id.get(link["source_iri"])
            target_id = iri_to_id.get(link["target_iri"])
            if source_id is None or target_id is None:
                skipped += 1
                continue
            rels.append(Relationship(source_entity_id=source_id,
                                     target_entity_id=target_id,
                                     name=link["name"], confidence=1.0))
        estore.save_relationships(rels)
        if skipped:
            logger.warning("rdf instance import: %d link(s) skipped "
                           "(reference outside the imported individuals)", skipped)
        type_ancestors = _build_type_ancestors(settings.rdb_dsn)
        project_graph(
            estore, FalkorStore(settings.graph_url, ws_graph(workspace_id)),
            type_ancestors=type_ancestors, workspace_id=workspace_id,
        )
    finally:
        estore.close()
    return len(ids), len(rels)


def import_doc(content: str, fmt_hint: str, filename: str,
               workspace_id: int = 1) -> dict[str, Any]:
    """Parse RDF/OWL into proposed types + hierarchy + axioms, AND any
    individuals + the relationships between them; persist all of it."""
    from aryx.ontology.rdf import format_for_extension
    from aryx.ontology.rdf.importer_full import parse_ontology_full
    from aryx.ontology.rdf.instance_importer import parse_instances
    from aryx.store.axiom_store import VALID_KINDS, AxiomStore
    fmt = fmt_hint or format_for_extension(filename) or "turtle"
    try:
        parsed = parse_ontology_full(content, fmt)
        instances = parse_instances(content, fmt)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    types = parsed["types"]
    hierarchy = parsed["hierarchy"]
    axioms = parsed["axioms"]
    entities = instances["entities"]
    links = instances["links"]

    if not types and not entities:
        return {"imported": 0, "types": [], "format": fmt,
                "message": "no owl:Class / rdfs:Class declarations or "
                          "individuals found"}

    known_type_names = {t.name for t in types}
    onto = OntologyStore(get_settings().rdb_dsn, workspace_id)
    try:
        onto.seed_types(types)
        implicit_types = _implicit_types_from_entities(entities, known_type_names)
        if implicit_types:
            onto.seed_types(implicit_types)
        for child, parent in hierarchy.items():
            onto.set_parent(child, parent)
    finally:
        onto.close()

    axiom_store = AxiomStore(get_settings().rdb_dsn)
    persisted = 0
    try:
        for ax in axioms:
            if ax["kind"] in VALID_KINDS and ax["subject_type"] != "_property":
                axiom_store.add(workspace_id, ax["subject_type"],
                                ax["kind"], ax["payload"])
                persisted += 1
    finally:
        axiom_store.close()

    entities_imported, relationships_imported = _ingest_instances(
        entities, links, workspace_id)

    all_type_names = sorted(known_type_names | {e["type"] for e in entities})
    message = ("imported entities + relationships into the graph; "
               "new types are 'proposed' — approve in the review gate"
               if entities_imported else
               "imported as 'proposed' — approve in the review gate")
    return {"imported": len(all_type_names), "types": all_type_names,
            "hierarchy_edges": len(hierarchy), "axioms_persisted": persisted,
            "entities_imported": entities_imported,
            "relationships_imported": relationships_imported,
            "format": fmt, "message": message}


def set_parent(name: str, parent: str | None,
                workspace_id: int = 1) -> dict[str, Any]:
    """Set or clear the parent_type for a type (rdfs:subClassOf)."""
    store = OntologyStore(get_settings().rdb_dsn, workspace_id)
    try:
        store.set_parent(name, parent)
    finally:
        store.close()
    return {"status": "ok", "name": name, "parent_type": parent}


def delete_type(name: str, workspace_id: int = 1) -> dict[str, Any]:
    """Remove a type from one workspace. Schema-level only — entity
    instances of this type are not deleted (callers handle separately)."""
    store = OntologyStore(get_settings().rdb_dsn, workspace_id)
    try:
        store.delete_type(name)
    finally:
        store.close()
    return {"status": "deleted", "name": name}


def list_browse(workspace_id: int) -> dict[str, Any]:
    """Return ontology types + relationship counts for one workspace."""
    settings = get_settings()
    onto = OntologyStore(settings.rdb_dsn, workspace_id)
    try:
        type_objs = onto.list_types()
        type_rows = [t.__dict__ if hasattr(t, "__dict__") else dict(t)
                     for t in type_objs]
        for row in type_rows:
            if row.get("parent_type"):
                row["ancestors"] = onto.ancestors(row["name"])
            else:
                row["ancestors"] = []
    finally:
        onto.close()
    store = EntityStore(settings.rdb_dsn, workspace_id)
    try:
        ents = store.list_entities()
        rels = store.list_relationships()
    finally:
        store.close()
    def _field(row: Any, key: str, idx: int) -> str:
        if isinstance(row, dict):
            return str(row.get(key) or row.get("ontology_type") or "?")
        try:
            return str(row[idx])
        except (IndexError, TypeError):
            return "?"
    per_type: dict[str, int] = {}
    for e in ents:
        per_type[_field(e, "type", 1)] = per_type.get(_field(e, "type", 1), 0) + 1
    for t in type_rows:
        t["instance_count"] = per_type.get(t.get("name"), 0)
    rel_types: dict[str, int] = {}
    for r in rels:
        rel_types[_field(r, "name", 2)] = rel_types.get(_field(r, "name", 2), 0) + 1
    return {
        "types": type_rows,
        "relationships": [{"name": k, "count": v} for k, v in rel_types.items()],
        "entity_count": len(ents),
    }
