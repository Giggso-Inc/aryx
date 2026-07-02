"""Bridge endpoints that make Shay a user-facing skin over Aryx."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from aryx.api.ask_api import AskRequest, Turn, run_ask
from aryx.api.security import require_api_key
from aryx.config import get_settings
from aryx.store.shay_bridge_store import ShayBridgeStore


class WorkspaceEnsureRequest(BaseModel):
    shay_workspace_id: str
    name: str
    description: str = ""
    company_id: str | None = None


class ShayChatAskRequest(BaseModel):
    shay_workspace_id: str
    shay_thread_id: str
    question: str


class ShayDatasourceSyncRequest(BaseModel):
    shay_workspace_id: str
    shay_datasource_id: str
    name: str
    kind: str = Field(..., description="Aryx datasource kind to create")
    config: dict[str, Any] = Field(default_factory=dict)
    secret: str | None = None
    ingest_job_id: str | None = None


def _citations_from_answer(answer: dict[str, Any]) -> list[dict[str, Any]]:
    grounding = answer.get("grounding") or {}
    citations = grounding.get("citations") or []
    return [c for c in citations if isinstance(c, dict)]


def shay_bridge_router() -> APIRouter:
    router = APIRouter(
        prefix="/admin/shay",
        dependencies=[Depends(require_api_key)],
    )

    @router.post("/workspaces/ensure")
    def ensure_workspace(req: WorkspaceEnsureRequest) -> dict[str, Any]:
        store = ShayBridgeStore(get_settings().rdb_dsn)
        try:
            return store.ensure_workspace_mapping(
                shay_workspace_id=req.shay_workspace_id,
                name=req.name,
                description=req.description,
                company_id=req.company_id,
            )
        finally:
            store.close()

    @router.get("/workspaces/{shay_workspace_id}/mapping")
    def get_workspace_mapping(shay_workspace_id: str) -> dict[str, Any]:
        store = ShayBridgeStore(get_settings().rdb_dsn)
        try:
            mapping = store.get_workspace_mapping(shay_workspace_id)
        finally:
            store.close()
        if not mapping:
            raise HTTPException(404, f"no Aryx mapping for Shay workspace {shay_workspace_id}")
        return mapping

    @router.post("/datasources/sync")
    def sync_datasource(req: ShayDatasourceSyncRequest) -> dict[str, Any]:
        store = ShayBridgeStore(get_settings().rdb_dsn)
        try:
            return store.sync_datasource(
                shay_workspace_id=req.shay_workspace_id,
                shay_datasource_id=req.shay_datasource_id,
                name=req.name,
                kind=req.kind,
                config=req.config,
                secret=req.secret,
                ingest_job_id=req.ingest_job_id,
            )
        finally:
            store.close()

    @router.post("/chats/ask")
    def ask_from_shay(req: ShayChatAskRequest) -> dict[str, Any]:
        store = ShayBridgeStore(get_settings().rdb_dsn)
        try:
            mapping = store.get_workspace_mapping(req.shay_workspace_id)
            if not mapping:
                raise HTTPException(404, f"no Aryx mapping for Shay workspace {req.shay_workspace_id}")

            aryx_workspace_id = int(mapping["aryx_workspace_id"])
            store.ensure_chat_mapping(
                shay_thread_id=req.shay_thread_id,
                shay_workspace_id=req.shay_workspace_id,
                aryx_workspace_id=aryx_workspace_id,
                ask_session_key=req.shay_thread_id,
            )
            history = [
                Turn(role=entry["role"], text=entry["text"])
                for entry in store.conversation_history(req.shay_thread_id)
            ]
            answer = run_ask(
                AskRequest(
                    question=req.question,
                    history=history,
                    workspace_id=aryx_workspace_id,
                )
            )
            citations = _citations_from_answer(answer)
            store.append_chat_turn(
                shay_thread_id=req.shay_thread_id,
                aryx_workspace_id=aryx_workspace_id,
                question=req.question,
                answer=answer.get("answer", ""),
                citations=citations,
                usage=answer.get("usage") or {},
                grounding=answer.get("grounding") or {},
            )
            return {
                "shay_thread_id": req.shay_thread_id,
                "shay_workspace_id": req.shay_workspace_id,
                "aryx_workspace_id": aryx_workspace_id,
                "answer": answer.get("answer", ""),
                "terms": answer.get("terms", []),
                "tools_called": answer.get("tools_called", []),
                "usage": answer.get("usage", {}),
                "grounding": answer.get("grounding"),
                "citations": citations,
            }
        finally:
            store.close()

    @router.get("/chats/history")
    def chat_history(
        shay_thread_id: str,
        limit: int = Query(50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        store = ShayBridgeStore(get_settings().rdb_dsn)
        try:
            return store.list_chat_turns(shay_thread_id, limit)
        finally:
            store.close()

    @router.get("/chats/threads")
    def chat_threads(
        shay_workspace_id: str,
        limit: int = Query(50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        store = ShayBridgeStore(get_settings().rdb_dsn)
        try:
            return store.list_workspace_threads(shay_workspace_id, limit)
        finally:
            store.close()

    return router
