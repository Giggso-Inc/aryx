"""Request models + citation extraction for the Shay bridge API.

Split out of `api/shay_bridge_api.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
