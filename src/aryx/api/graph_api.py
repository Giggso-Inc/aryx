"""FastAPI read API over the FalkorDB knowledge graph (Increment 6)."""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from aryx.api.security import require_api_key
from aryx.config import get_settings
from aryx.graph import GraphReader
from aryx.ports import ports
from aryx.workspaces import ws_graph

_WRITE_KEYWORDS_RE = re.compile(
    r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DROP|DETACH)\b", re.IGNORECASE)
_READ_LEAD_RE = re.compile(
    r"^\s*(MATCH|WITH|RETURN|CALL|UNWIND)\b", re.IGNORECASE)
_HAS_LIMIT_RE = re.compile(r"\bLIMIT\b", re.IGNORECASE)
_HAS_RETURN_RE = re.compile(r"\bRETURN\b", re.IGNORECASE)
_ALLOWED_CALL_PROCEDURES = frozenset({
    "db.idx.fulltext.querynodes",
    "db.labels",
    "db.propertykeys",
    "db.relationshiptypes",
    "db.indexes",
})
_CALL_PROCEDURE_RE = re.compile(r"\bCALL\s+([A-Za-z_][A-Za-z0-9_.]*)\s*\(", re.IGNORECASE)


def _find_disallowed_call(query: str) -> str | None:
    """Return the first non-read-only Cypher procedure, if one is present."""
    for match in _CALL_PROCEDURE_RE.finditer(query):
        name = match.group(1)
        if name.lower() not in _ALLOWED_CALL_PROCEDURES:
            return name
    return None


class CypherRequest(BaseModel):
    """External contract for a bounded, parameterized graph read."""

    workspace_id: int
    query: str
    params: dict[str, Any] = Field(default_factory=dict)
    limit: int | None = Field(default=50, ge=1)
    timeout_ms: int | None = Field(default=None, ge=1)


def _reader(workspace_id: int = 1) -> GraphReader:
    return ports().graph_reader(workspace_id)  # type: ignore[return-value]


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
    def full_graph(reader: GraphReader = Depends(_reader)) -> dict[str, Any]:
        """All entities + all relationships in one call (for graph canvas)."""
        return {
            "entities": reader.find_entities(limit=500),
            "relationships": reader.all_relationships(),
        }

    @router.post("/graph/cypher")
    def cypher_read(
        body: CypherRequest, _: str = Depends(require_api_key),
    ) -> dict[str, Any]:
        """Run an authenticated, bounded, parameterized read-only query."""
        query = body.query.strip()
        if not query:
            raise HTTPException(400, "query must not be empty")
        if _WRITE_KEYWORDS_RE.search(query):
            raise HTTPException(400, "read-only — write keywords rejected")
        if not _READ_LEAD_RE.match(query):
            raise HTTPException(
                400, "query must start with MATCH, WITH, RETURN, CALL, or UNWIND")
        disallowed_call = _find_disallowed_call(query)
        if disallowed_call is not None:
            raise HTTPException(
                400, f"procedure {disallowed_call!r} is not on the read-only allowlist")

        hard_cap = get_settings().graph_query_limit
        effective_limit = min(body.limit, hard_cap) if body.limit is not None else hard_cap
        needs_limit = _HAS_RETURN_RE.search(query) and not _HAS_LIMIT_RE.search(query)
        query_to_run = f"{query} LIMIT {effective_limit}" if needs_limit else query
        reader = GraphReader(get_settings().graph_url, ws_graph(body.workspace_id))
        try:
            columns, rows = reader.run_readonly(
                query_to_run, body.params, body.timeout_ms)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"cypher failed: {exc}") from exc
        limited_rows = rows[:effective_limit]
        return {
            "workspace_id": body.workspace_id,
            "row_count": len(limited_rows),
            "limited": len(rows) > effective_limit,
            "columns": columns,
            "rows": [dict(zip(columns, row)) for row in limited_rows],
        }

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
