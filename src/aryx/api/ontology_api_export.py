"""GraphBundle loading + RDF/OWL export response for the ontology API.

Split out of `api/ontology_api.py` (Raven Style Compliance Plan, Phase
2b, 2026-09-03). Zero test patches against this module — confirmed via
grep.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException, Response

from aryx import export_runtime
from aryx.config import get_settings
from aryx.ontology.rdf import GraphBundle, serialize
from aryx.store.axiom_store import AxiomStore
from aryx.store.entity_store import EntityStore
from aryx.store.ontology_store import OntologyStore

logger = logging.getLogger(__name__)


def _load_bundle(workspace_id: int, include_provenance: bool) -> GraphBundle:
    """Read a workspace's graph from Postgres into a GraphBundle."""
    settings = get_settings()
    store = EntityStore(settings.effective_dsn(), workspace_id)
    try:
        provenance = list(store.list_members_provenance()) if include_provenance else []
        bundle = GraphBundle(
            entities=list(store.list_entities()),
            relationships=list(store.list_relationships()),
            provenance=provenance,
        )
    finally:
        store.close()
    onto = OntologyStore(settings.effective_dsn(), workspace_id)
    try: bundle.types = onto.list_types()
    finally: onto.close()
    axiom_store = AxiomStore(settings.effective_dsn())
    try: bundle.axioms = axiom_store.list_(workspace_id)
    finally: axiom_store.close()
    return bundle


def export_graph_response(workspace_id: int, format: str) -> Response:
    """Serialise a workspace graph to RDF/OWL as a downloadable file."""
    if not export_runtime.is_enabled():
        raise HTTPException(403, "ontology export is disabled — enable it in Settings")
    if format not in export_runtime.enabled_formats():
        raise HTTPException(403, f"format '{format}' is not enabled in Settings")
    cap = get_settings().ontology_export_max_entities
    if cap > 0:
        settings = get_settings()
        _estore = EntityStore(settings.effective_dsn(), workspace_id)
        try:
            entity_count = _estore.count_entities()
        finally:
            _estore.close()
        if entity_count > cap:
            raise HTTPException(
                413,
                f"workspace {workspace_id} has {entity_count:,} entities — "
                f"synchronous export is capped at {cap:,} to prevent proxy "
                f"timeouts (502). Raise ARYX_ONTOLOGY_EXPORT_MAX_ENTITIES or "
                f"use the async export endpoint.",
            )
    cfg = export_runtime.status()
    try:
        bundle = _load_bundle(workspace_id, bool(cfg["include_provenance"]))
        payload, media_type, ext = serialize(
            bundle, format, str(cfg["base_uri"]), bool(cfg["include_provenance"]),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface store/serialise faults
        logger.warning("ontology export failed: %s", exc)
        raise HTTPException(500, f"export failed: {exc}") from exc
    filename = f"aryx_ws{workspace_id}.{ext}"
    return Response(
        content=payload, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
