"""Ontology interchange API — RDF/OWL export + import; ontology CRUD.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`ontology_api_models.py` (request models) and `ontology_api_export.py`
(`_load_bundle`/`export_graph_response`), both re-imported here. Zero
whitebox test patches exist anywhere against `aryx.api.ontology_api.*`
(confirmed via grep), so the split was purely mechanical.
`ontology_router` — wiring the routes — stays here.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response

from aryx import export_runtime
from aryx.api import ontology_browse as _ob
from aryx.api.ontology_api_export import export_graph_response
from aryx.api.ontology_api_models import OntologyConfigRequest, OntologyImportRequest
from aryx.api.security import write_api_key
from aryx.config import get_settings
from aryx.graph import FalkorStore
from aryx.ontology.rdf import available_formats
from aryx.store.entity_store import EntityStore
from aryx.workspaces import ws_graph

__all__ = ["OntologyConfigRequest", "OntologyImportRequest", "ontology_router"]

logger = logging.getLogger(__name__)


def ontology_router() -> APIRouter:
    """Build the /ontology router (config, formats, export, import)."""
    router = APIRouter(prefix="/ontology")

    @router.get("/config")
    def get_config() -> dict:
        """Return the current interchange config + available formats."""
        return export_runtime.status()

    @router.post("/config")
    def set_config(req: OntologyConfigRequest,
                   _: str | None = Depends(write_api_key)) -> dict:
        """Update the interchange config (enable, formats, base URI)."""
        export_runtime.set_config(
            enabled=req.enabled, formats=req.formats,
            base_uri=req.base_uri, include_provenance=req.include_provenance,
        )
        return export_runtime.status()

    @router.get("/formats")
    def list_formats() -> list[dict[str, str]]:
        """List every supported format with its media type and extension."""
        return available_formats()

    @router.get("/types")
    def list_types(workspace_id: int = 1) -> dict:
        """Return ontology types + relationships (Browse tab)."""
        return _ob.list_browse(workspace_id)

    @router.post("/types/{name}/approve")
    def approve_type(name: str, workspace_id: int = 1,
                      _: str | None = Depends(write_api_key)) -> dict:
        """Approve a proposed type."""
        return _ob.approve(name, workspace_id)

    @router.post("/types/{name}/parent")
    def set_parent(name: str, body: dict,
                    workspace_id: int = 1,
                    _: str | None = Depends(write_api_key)) -> dict:
        """Set or clear parent_type (body.parent str|null)."""
        parent = body.get("parent")
        return _ob.set_parent(name, str(parent) if parent else None,
                                workspace_id)

    @router.post("/types")
    def add_type(body: dict, _: str | None = Depends(write_api_key)) -> dict:
        """Create a new ontology type manually in one workspace."""
        return _ob.add_type(str(body.get("name", "")).strip(),
                            body.get("attributes") or {},
                            str(body.get("status", "approved")),
                            workspace_id=int(body.get("workspace_id", 1)))

    @router.delete("/types/{name}")
    def delete_type(name: str, workspace_id: int = 1,
                    _: str | None = Depends(write_api_key)) -> dict:
        """Remove a type and cascade: delete all its entity instances from
        Postgres and remove their nodes from FalkorDB, then drop the type."""
        settings = get_settings()
        estore = EntityStore(settings.effective_dsn(), workspace_id)
        try:
            deleted_ids = estore.delete_entities_by_type(name)
        finally:
            estore.close()
        FalkorStore(settings.graph_url, ws_graph(workspace_id)).remove_entities_by_type(name)
        logger.info("type delete cascade ws=%s type=%s entities=%d",
                    workspace_id, name, len(deleted_ids))
        return {**_ob.delete_type(name, workspace_id), "entities_deleted": len(deleted_ids)}

    @router.get("/export")
    def export_graph(workspace_id: int = 1, format: str = "turtle") -> Response:
        """Serialise a workspace graph to RDF/OWL as a downloadable file."""
        return export_graph_response(workspace_id, format)

    @router.post("/import")
    def import_ontology(req: OntologyImportRequest,
                         _: str | None = Depends(write_api_key)) -> dict:
        """Parse RDF/OWL into proposed types via the ontology_browse helper."""
        if not export_runtime.is_enabled():
            raise HTTPException(403, "ontology import disabled — enable in Settings")
        try:
            return _ob.import_doc(req.content, req.format, req.filename,
                                  req.workspace_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    return router
