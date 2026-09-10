"""Request models for the admin API.

Split out of `api/admin_api.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class EntityCreateRequest(BaseModel):
    ontology_type: str
    attributes: dict[str, Any] = {}
    workspace_id: int = 1


class EntityUpdateRequest(BaseModel):
    attributes: dict[str, Any]


class FkLink(BaseModel):
    source_type: str
    source_attr: str
    target_type: str
    target_attr: str
    name: str


class IngestDbRequest(BaseModel):
    table: str
    ontology_type: str
    match_keys: str
    system: str = "postgresql"
    key_column: str = "id"
    fk_links: list[FkLink] = []
    workspace_id: int = 1
