"""Forwards a generated CPQ config payload to a partner system.

Unlike a fixed server-side integration, the destination is supplied by the
caller per share (endpoint URL + auth header) — the same trust model already
used by the REST API ingest form (components/ingest/RestConfigForm.tsx),
including the same SSRF guard: endpoint_url and extra_headers are validated
by the shared aryx.api.ssrf_guard checks, not just a non-empty check. The
browser collects the destination, our backend relays it, nothing is persisted.
"""
from __future__ import annotations

import logging
import urllib.error
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from aryx.api.ssrf_guard import BLOCKED_HEADERS, check_outbound_headers, check_outbound_url
from aryx.llm_providers import post_json

logger = logging.getLogger(__name__)


class ShareConfigRequest(BaseModel):
    workspace_id: int
    conversation_id: str
    config_json: dict[str, Any]
    endpoint_url: str
    auth_header_name: str = "Authorization"
    auth_header_value: str = ""
    extra_headers: dict[str, str] = {}

    @field_validator("endpoint_url")
    @classmethod
    def _no_ssrf(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("endpoint_url is required")
        return check_outbound_url(v)

    @field_validator("extra_headers")
    @classmethod
    def _safe_extra_headers(cls, v: dict[str, str]) -> dict[str, str]:
        return check_outbound_headers(v)

    @field_validator("auth_header_name")
    @classmethod
    def _safe_auth_header_name(cls, v: str) -> str:
        if v.strip().lower() in BLOCKED_HEADERS:
            raise ValueError(f"auth_header_name may not be: {v}")
        return v


def share_config_router() -> APIRouter:
    router = APIRouter()

    @router.post("/share-config")
    def share_config(req: ShareConfigRequest) -> dict:
        headers = dict(req.extra_headers)
        if req.auth_header_value:
            headers[req.auth_header_name or "Authorization"] = req.auth_header_value
        try:
            resp = post_json(req.endpoint_url, req.config_json, headers=headers)
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            logger.warning(
                "share-config forward failed (workspace_id=%s, conversation_id=%s): %s",
                req.workspace_id, req.conversation_id, exc,
            )
            raise HTTPException(502, "partner API unreachable") from exc
        return {"shared": True, "partner_response": resp}

    return router
