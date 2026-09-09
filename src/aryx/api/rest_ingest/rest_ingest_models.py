"""Request models for the REST-endpoint ingest API.

Split out of `api/rest_ingest_api.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from aryx.api.ssrf_guard import check_outbound_headers, check_outbound_url


class RestPreviewRequest(BaseModel):
    workspace_id: int = 1
    url: str
    headers: dict[str, str] = {}
    record_path: str = ""
    page_param: str = ""
    next_page_path: str = ""
    context: str = ""

    @field_validator("url")
    @classmethod
    def _no_ssrf(cls, v: str) -> str:
        return check_outbound_url(v)

    @field_validator("headers")
    @classmethod
    def _safe_headers(cls, v: dict[str, str]) -> dict[str, str]:
        return check_outbound_headers(v)


class RestIngestRequest(BaseModel):
    workspace_id: int = 1
    url: str
    headers: dict[str, str] = {}
    record_path: str = ""
    page_param: str = ""
    next_page_path: str = ""
    max_pages: int = Field(default=20, ge=1, le=500)
    ontology_type: str = ""
    match_keys: list[str] = ["id"]
    context: str = ""

    @field_validator("url")
    @classmethod
    def _no_ssrf(cls, v: str) -> str:
        return check_outbound_url(v)

    @field_validator("headers")
    @classmethod
    def _safe_headers(cls, v: dict[str, str]) -> dict[str, str]:
        return check_outbound_headers(v)
