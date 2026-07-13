"""Forwards a generated CPQ config payload to a partner system.

Unlike a fixed server-side integration, the destination is supplied by the
caller per share (endpoint URL + auth header) — the same trust model already
used by the REST API ingest form (components/ingest/RestConfigForm.tsx):
the browser collects it, our backend relays it, nothing is persisted.
"""
from __future__ import annotations

import logging
import urllib.error
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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


def share_config_router() -> APIRouter:
    router = APIRouter()

    @router.post("/share-config")
    def share_config(req: ShareConfigRequest) -> dict:
        if not req.endpoint_url.strip():
            raise HTTPException(422, "endpoint_url is required")
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
