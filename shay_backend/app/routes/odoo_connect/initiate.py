"""
GET /connect/initiate — return a form_url pointing to the shay_backend-hosted
Odoo credential form.

Split from the original app/routes/odoo_connect.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

import secrets
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.services.sso_service import build_state, is_allowed_redirect_uri

from .state import _SID_RE, _prune_token_store, _sid_token_store

router = APIRouter()


@router.get("/connect/initiate")
async def odoo_connect_initiate(
    request: Request,
    sid: str = Query(..., description="MCP session ID"),
    redirect_uri: str = Query(..., description="MCP odoo callback URL"),
) -> JSONResponse:
    """Return a form_url — the shay_backend-hosted Odoo credential form."""
    if not _SID_RE.match(sid):
        return JSONResponse({"error": "invalid_sid"}, status_code=400)
    if not is_allowed_redirect_uri(redirect_uri):
        return JSONResponse({"error": "invalid_redirect_uri"}, status_code=400)

    # Store the MCP user's Bearer token so the complete endpoint can forward it
    # to the orchestrator — same token already used for all other BE API calls.
    _prune_token_store()
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        _sid_token_store[sid] = (auth_header[len("Bearer "):], time.monotonic())

    csrf_token = secrets.token_urlsafe(32)
    # invite_id slot carries the MCP session ID here (not a user invite UUID).
    state = build_state(invite_id=sid, redirect_uri=redirect_uri, csrf_token=csrf_token)

    base = (settings.SHAY_BE_PUBLIC_URL or str(request.base_url)).rstrip("/")
    form_url = f"{base}/api/v1/odoo/connect/form?state={state}"

    response = JSONResponse({"form_url": form_url})
    response.set_cookie("sso_csrf", csrf_token, max_age=600, httponly=True, samesite="lax")
    return response
