"""Generic authenticated entity read, create, and update endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from aryx.api.security import require_api_key
from aryx.config import get_settings
from aryx.store.entity_store import EntityStore


def _allowed_workspace_ids() -> set[int] | None:
    """Return an optional configured workspace restriction for management routes."""
    raw_ids = get_settings().entity_management_allowed_workspace_ids
    values = [value.strip() for value in raw_ids.split(",") if value.strip()]
    return {int(value) for value in values} if values else None


def _ensure_workspace_allowed(workspace_id: int) -> None:
    """Reject an operation outside an optional configured workspace restriction."""
    allowed_workspace_ids = _allowed_workspace_ids()
    if allowed_workspace_ids is not None and workspace_id not in allowed_workspace_ids:
        raise HTTPException(403, "entity management is not enabled for this workspace")


def _store(workspace_id: int) -> EntityStore:
    """Construct the entity source-of-truth store for one workspace."""
    return EntityStore(get_settings().rdb_dsn, workspace_id)


def _reproject(workspace_id: int) -> dict[str, int]:
    """Synchronize the workspace graph after a source-of-truth mutation."""
    from aryx.graph.falkor_store import FalkorStore
    from aryx.project import project_graph
    from aryx.workspaces import ws_graph

    settings = get_settings()
    store = _store(workspace_id)
    graph = FalkorStore(settings.graph_url, ws_graph(workspace_id))
    return project_graph(store, graph, workspace_id=workspace_id)


class EntityCreateRequest(BaseModel):
    """Generic source-of-truth entity creation contract."""

    workspace_id: int = Field(gt=0)
    ontology_type: str = Field(min_length=1, max_length=128)
    attributes: dict[str, Any] = Field(min_length=1)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reproject: bool = True


class EntityUpdateRequest(BaseModel):
    """Generic source-of-truth entity replacement contract."""

    attributes: dict[str, Any] = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reproject: bool = True


def _response(workspace_id: int, entity: tuple, *, projected: dict[str, int] | None = None) -> dict:
    """Shape one database entity into the public management response."""
    entity_id, ontology_type, attributes, confidence, created_at, updated_at = entity
    result = {
        "id": entity_id,
        "workspace_id": workspace_id,
        "ontology_type": ontology_type,
        "attributes": attributes,
        "confidence": confidence,
        "created_at": created_at,
        "updated_at": updated_at,
    }
    if projected is not None:
        result["projected"] = projected
    return result


def entity_management_router() -> APIRouter:
    """Build generic entity-management routes under the admin API namespace."""
    router = APIRouter(prefix="/admin/entities")

    @router.get("/{entity_id}")
    def get_entity(
        entity_id: int,
        workspace_id: int = Query(gt=0),
        _: str = Depends(require_api_key),
    ) -> dict:
        """Read one workspace-scoped entity from the relational source of truth."""
        _ensure_workspace_allowed(workspace_id)
        store = _store(workspace_id)
        try:
            entity = store.get_entity(entity_id)
        finally:
            store.close()
        if entity is None:
            raise HTTPException(404, "entity not found")
        return _response(workspace_id, entity)

    @router.post("", status_code=201)
    def create_entity(
        request: EntityCreateRequest,
        _: str = Depends(require_api_key),
    ) -> dict:
        """Create an entity and optionally synchronize its FalkorDB projection."""
        _ensure_workspace_allowed(request.workspace_id)
        store = _store(request.workspace_id)
        try:
            entity = store.create_entity(
                request.ontology_type, request.attributes, request.confidence)
        finally:
            store.close()
        projected = _reproject(request.workspace_id) if request.reproject else None
        return _response(request.workspace_id, entity, projected=projected)

    @router.put("/{entity_id}")
    def update_entity(
        entity_id: int,
        request: EntityUpdateRequest,
        workspace_id: int = Query(gt=0),
        _: str = Depends(require_api_key),
    ) -> dict:
        """Replace entity attributes and optionally synchronize FalkorDB."""
        _ensure_workspace_allowed(workspace_id)
        store = _store(workspace_id)
        try:
            entity = store.update_entity(entity_id, request.attributes, request.confidence)
        finally:
            store.close()
        if entity is None:
            raise HTTPException(404, "entity not found")
        projected = _reproject(workspace_id) if request.reproject else None
        return _response(workspace_id, entity, projected=projected)

    return router
