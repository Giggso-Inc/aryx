"""FastAPI read API over the FalkorDB knowledge graph (Increment 6)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException

from aryx import explore
from aryx.config import get_settings
from aryx.graph import GraphReader
from aryx.ports import ports
from aryx.store.entity_store import EntityStore
from aryx.workspaces import make_workspace_store


def _reader(workspace_id: int = 1) -> GraphReader:
    # Default workspace 1 = "Default". Callers pass ?workspace_id= to select
    # a different workspace.  Multi-tenant deployments should derive this from
    # the auth context instead of relying on the query-param default.
    return ports().graph_reader(workspace_id)  # type: ignore[return-value]


def _brief_for(workspace_id: int) -> dict[str, Any]:
    """Return the saved workspace brief so overview mode can stay in sync."""
    store = make_workspace_store(get_settings().rdb_dsn)
    try:
        for workspace in store.list_all():
            if int(workspace.get("id", 0)) == int(workspace_id):
                return workspace.get("brief") or {}
    finally:
        store.close()
    return {}


def _overview_payload(workspace_id: int) -> dict[str, Any]:
    """Build the brief-driven graph overview from the relational truth."""
    store = EntityStore(get_settings().rdb_dsn, workspace_id)
    try:
        return explore.domain_overview_view(
            store.list_entities(),
            store.list_relationships(),
            _brief_for(workspace_id),
        )
    finally:
        store.close()


def graph_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/entities")
    def find_entities(
        type: str | None = None, name: str | None = None, limit: int = 50,
        reader: GraphReader = Depends(_reader),
    ) -> list[dict[str, Any]]:
        return reader.find_entities(ontology_type=type, name=name, limit=limit)

    @router.get("/graph")
    def full_graph(
        rel_limit: int = 2000,
        reader: GraphReader = Depends(_reader),
    ) -> dict[str, Any]:
        """Connected subgraph for graph canvas rendering.

        Returns up to *rel_limit* relationships and the entities at their
        endpoints.  Every returned entity has at least one edge, so the
        graph-canvas layout algorithm produces a proper connected diagram
        instead of a linear list of orphan nodes.
        """
        return reader.subgraph(rel_limit=rel_limit)

    @router.get("/graph/overview")
    def graph_overview(workspace_id: int = 1) -> dict[str, Any]:
        """Brief-driven overview graph plus domain highlight metadata."""
        return _overview_payload(workspace_id)

    @router.post("/graph/cypher")
    def cypher_read(body: dict[str, Any]) -> dict[str, Any]:
        """Run a read-only Cypher MATCH; rejects writes (server.py also guards)."""
        import re as _re
        q = str(body.get("query") or "")
        if _re.search(r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DROP|DETACH)\b",
                      q, _re.IGNORECASE):
            raise HTTPException(400, "read-only — write keywords rejected")
        wid = int(body.get("workspace_id", 1))
        from aryx.graph.falkor_store import FalkorStore
        from aryx.workspaces import ws_graph
        store = FalkorStore(get_settings().graph_url, ws_graph(wid))
        try:
            rows = store.run(q, params={})
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"cypher failed: {exc}") from exc
        return {"rows": rows[: int(body.get("limit", 50))]}

    @router.get("/entities/{entity_id}")
    def get_entity(
        entity_id: int, reader: GraphReader = Depends(_reader)
    ) -> dict[str, Any]:
        entity = reader.get_entity(entity_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="entity not found")
        return entity

    @router.get("/entities/{entity_id}/neighbors")
    def neighbors(
        entity_id: int, reader: GraphReader = Depends(_reader)
    ) -> list[dict[str, Any]]:
        return reader.neighbors(entity_id)

    @router.get("/entities/{entity_id}/provenance")
    def provenance(
        entity_id: int, reader: GraphReader = Depends(_reader)
    ) -> list[dict[str, Any]]:
        return reader.provenance(entity_id)

    @router.get("/entities/{entity_id}/path/{target_id}")
    def path(
        entity_id: int, target_id: int, max_hops: int = 6,
        reader: GraphReader = Depends(_reader),
    ) -> list[dict[str, Any]]:
        return reader.shortest_path(entity_id, target_id, max_hops)

    return router


def create_app() -> FastAPI:
    app = FastAPI(title="Aryx Graph API", version="1.0")
    app.include_router(graph_router())
    return app


app = create_app()
