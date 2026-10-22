"""Data Explorer API (v2) — the transparency surface over resolved entities.

Reads the relational source of truth (EntityStore) so every row carries its
golden-record attributes and the source records it traces back to. Pure shaping
lives in aryx.explore; this module is the thin HTTP wire.
"""
from __future__ import annotations

import hashlib
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from aryx import explore
from aryx.api.security import require_api_key
from aryx.config import get_settings
from aryx.store.entity_store import EntityStore

logger = logging.getLogger(__name__)


def _allowed_catalog_workspace_ids() -> set[int] | None:
    """Return an optional configured workspace restriction for catalog snapshots."""
    raw_ids = get_settings().catalog_allowed_workspace_ids
    values = [value.strip() for value in raw_ids.split(",") if value.strip()]
    return {int(value) for value in values} if values else None


class FkLink(BaseModel):
    source_type: str
    source_attr: str
    target_type: str
    target_attr: str
    name: str


class RelateRequest(BaseModel):
    workspace_id: int = 1
    links: list[FkLink] = []
    replace: bool = True
    reproject: bool = True


def _store(workspace_id: int) -> EntityStore:
    return EntityStore(get_settings().rdb_dsn, workspace_id)


def data_router() -> APIRouter:
    router = APIRouter(prefix="/data")

    @router.get("/summary")
    def summary(workspace_id: int = 1) -> dict:
        """Type counts, source breakdown, and the dedup story."""
        store = _store(workspace_id)
        try:
            return explore.summarize(store.list_entities(),
                                     store.list_members_provenance())
        except Exception as exc:  # noqa: BLE001 — surface to the Data UI
            logger.warning("data summary failed: %s", exc)
            return {"error": f"data unavailable: {exc}"}

    @router.get("/entities")
    def entities(
        workspace_id: int = 1,
        type: list[str] | None = Query(default=None),
        attribute: str | None = Query(default=None, max_length=128),
        value: str | None = Query(default=None, max_length=200),
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Entities filtered by one or more types and an exact attribute."""
        if bool(attribute) != bool(value):
            raise HTTPException(422, "attribute and value must be supplied together")
        store = _store(workspace_id)
        try:
            return explore.entities_view(
                store.list_entities(), store.list_members_provenance(),
                ontology_types=set(type or ()), attribute_name=attribute,
                attribute_value=value, limit=limit, offset=offset)
        except Exception as exc:  # noqa: BLE001
            logger.warning("data entities failed: %s", exc)
            return {"error": f"data unavailable: {exc}", "items": []}

    @router.get("/catalog-entities")
    def catalog_entities(
        workspace_id: int,
        types: list[str] = Query(min_length=1, max_length=32),
        include_sources: bool = True,
        _: str = Depends(require_api_key),
    ) -> dict:
        """Return a bounded, type-scoped catalog snapshot for one workspace."""
        allowed_workspace_ids = _allowed_catalog_workspace_ids()
        if allowed_workspace_ids is not None and workspace_id not in allowed_workspace_ids:
            raise HTTPException(403, "catalog access is not enabled for this workspace")
        normalized_types = sorted({item.strip() for item in types if item.strip()})
        if not normalized_types:
            raise HTTPException(422, "at least one non-empty type is required")

        store = _store(workspace_id)
        try:
            entity_count = store.count_catalog_entities(normalized_types)
            max_entities = get_settings().catalog_max_entities
            if entity_count > max_entities:
                raise HTTPException(
                    413, f"catalog snapshot exceeds the {max_entities} entity limit")
            entities, provenance = store.list_catalog_entities(
                normalized_types, include_sources=include_sources)
        finally:
            store.close()

        by_entity: dict[int, list[dict]] = {}
        if include_sources:
            for entity_id, system, dataset, record_id in provenance:
                by_entity.setdefault(int(entity_id), []).append({
                    "system": system,
                    "dataset": dataset,
                    "record_id": str(record_id),
                })
        items = [
            {
                "id": entity_id,
                "type": ontology_type,
                "attributes": attributes or {},
                "sources": by_entity.get(int(entity_id), []),
            }
            for entity_id, ontology_type, attributes in entities
        ]
        revision_payload = json.dumps(
            items, sort_keys=True, default=str, separators=(",", ":"))
        return {
            "workspaceId": workspace_id,
            "types": normalized_types,
            "revision": hashlib.sha256(revision_payload.encode("utf-8")).hexdigest()[:16],
            "items": items,
        }

    @router.get("/entity/{entity_id}")
    def entity(entity_id: int, workspace_id: int = 1) -> dict:
        """One entity's attributes, source records, and relationships."""
        store = _store(workspace_id)
        try:
            detail = explore.entity_detail(
                store.list_entities(), store.list_members_provenance(),
                store.list_relationships(), entity_id)
            return detail or {"error": "entity not found"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("data entity detail failed: %s", exc)
            return {"error": f"detail unavailable: {exc}"}

    @router.get("/graph")
    def graph(workspace_id: int = 1, level: str = "type") -> dict:
        """Knowledge map. level=type → aggregated shape; level=entity → per-entity."""
        store = _store(workspace_id)
        try:
            if level == "entity":
                return explore.entity_graph_view(store.list_entities(),
                                                 store.list_relationships())
            return explore.graph_view(store.list_entities(),
                                      store.list_relationships())
        except Exception as exc:  # noqa: BLE001
            logger.warning("data graph failed: %s", exc)
            return {"error": f"graph unavailable: {exc}",
                    "type_nodes": [], "type_edges": [], "nodes": [], "edges": []}

    @router.post("/relate")
    def relate(req: RelateRequest) -> dict:
        """Derive relationships from foreign-key attribute links, then reproject.

        Each link creates edges where source_type.source_attr ==
        target_type.target_attr (exact, no LLM). Idempotent with replace=True.
        """
        from aryx.pipeline.fk_edges import link_by_attribute

        store = _store(req.workspace_id)
        try:
            cleared = store.clear_relationships() if req.replace else 0
            created = 0
            per_link = []
            for link in req.links:
                n = link_by_attribute(store, link.source_type, link.source_attr,
                                      link.target_type, link.target_attr, link.name)
                per_link.append({"name": link.name, "created": n})
                created += n
            projected = _reproject(req.workspace_id, store) if req.reproject else None
            return {"cleared": cleared, "created": created,
                    "per_link": per_link, "projected": projected}
        except Exception as exc:  # noqa: BLE001
            logger.warning("data relate failed: %s", exc)
            return {"error": f"relate failed: {exc}"}

    return router


def _reproject(workspace_id: int, store: EntityStore) -> dict:
    """Rebuild the FalkorDB projection so the graph reflects new edges."""
    from aryx.graph.falkor_store import FalkorStore
    from aryx.naming import ws_graph
    from aryx.project import project_graph

    falkor = FalkorStore(get_settings().graph_url, ws_graph(workspace_id))
    return project_graph(store, falkor, workspace_id=workspace_id)
