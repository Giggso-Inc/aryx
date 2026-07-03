"""Browse helper for the ontology API — types, attrs, relationship counts.

Workspace-scoped: every entry-point takes the workspace_id and threads it
through the OntologyStore so DEMO's types never appear in Default and
vice-versa.
"""
from __future__ import annotations

from typing import Any

from aryx.config import get_settings
from aryx.store.entity_store import EntityStore
from aryx.store.ontology_store import OntologyStore


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


def import_doc(content: str, fmt_hint: str, filename: str,
               workspace_id: int = 1) -> dict[str, Any]:
    """Parse RDF/OWL into proposed types + hierarchy + axioms; persist all."""
    from aryx.ontology.rdf import format_for_extension
    from aryx.ontology.rdf.importer_full import parse_ontology_full
    from aryx.store.axiom_store import VALID_KINDS, AxiomStore
    fmt = fmt_hint or format_for_extension(filename) or "turtle"
    try:
        parsed = parse_ontology_full(content, fmt)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    types = parsed["types"]
    hierarchy = parsed["hierarchy"]
    axioms = parsed["axioms"]
    if not types:
        return {"imported": 0, "types": [], "format": fmt,
                "message": "no owl:Class / rdfs:Class declarations found"}
    onto = OntologyStore(get_settings().rdb_dsn, workspace_id)
    try:
        onto.seed_types(types)
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
    return {"imported": len(types), "types": [t.name for t in types],
            "hierarchy_edges": len(hierarchy), "axioms_persisted": persisted,
            "format": fmt,
            "message": "imported as 'proposed' — approve in the review gate"}


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
    """Return ontology types + relationship counts for one workspace.

    Auto-heal: when the ontology type registry is empty but entities exist
    (e.g. data ingested before type-seeding was introduced), derive types
    from distinct ontology_type values in the entity store and persist them
    as approved. Idempotent — uses ON CONFLICT DO NOTHING.
    """
    from aryx.models import OntologyType as _OT
    import logging as _logging
    _log = _logging.getLogger(__name__)

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
        ents = list(store.list_entities())
        rels = list(store.list_relationships())
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

    # Auto-heal: seed missing type registry from entity store data.
    if not type_rows and per_type:
        _log.info("ontology_browse: no types found for ws=%s but %d entity types exist — auto-seeding",
                  workspace_id, len(per_type))
        heal_onto = OntologyStore(settings.rdb_dsn, workspace_id)
        try:
            heal_onto.seed_types([
                _OT(name=name, attributes=[], status="approved", source="entity-store")
                for name in per_type
            ])
            healed = heal_onto.list_types()
            type_rows = [t.__dict__ if hasattr(t, "__dict__") else dict(t) for t in healed]
            for row in type_rows:
                row["ancestors"] = []
        except Exception:  # noqa: BLE001
            _log.warning("ontology_browse: auto-heal seed failed for ws=%s", workspace_id, exc_info=True)
        finally:
            heal_onto.close()

    for t in type_rows:
        t["instance_count"] = per_type.get(t.get("name"), 0)
    rel_types: dict[str, int] = {}
    for r in rels:
        rel_types[_field(r, "name", 2)] = rel_types.get(_field(r, "name", 2), 0) + 1
    return {
        "types": type_rows,
        "relationships": [{"name": k, "count": v} for k, v in rel_types.items()],
        "entity_count": sum(per_type.values()),
    }
