"""
POST /connect/complete — verify Odoo credentials via orchestrator, then
redirect to the MCP callback with the connection data in the URL fragment.

Split from the original app/routes/odoo_connect.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import settings
from app.services.sso_service import verify_state

from .state import _encode_payload, _prune_token_store, _sid_token_store

router = APIRouter()


@router.post("/connect/complete")
async def odoo_connect_complete(
    request: Request,
    state: str = Form(...),
    odoo_url: str = Form(...),
    database: str = Form(...),
    username: str = Form(...),
    api_key: str = Form(...),
) -> RedirectResponse:
    """
    Verify Odoo credentials via orchestrator, then redirect to the MCP callback
    with the connection data encoded in the URL fragment.
    """
    _prune_token_store()
    cookie_csrf = request.cookies.get("sso_csrf")

    try:
        state_data = verify_state(state, cookie_csrf)
    except Exception:
        return HTMLResponse(
            "<p style='font-family:sans-serif;padding:32px;color:#c00'>"
            "Session expired. Please start over from Claude.</p>",
            status_code=400,
        )

    sid = state_data.get("invite_id", "")
    mcp_redirect_uri = state_data.get("redirect_uri", "")

    def _error_redirect(msg: str) -> RedirectResponse:
        fragment = urlencode({"error": msg, "_sid": sid})
        r = RedirectResponse(url=f"{mcp_redirect_uri}#{fragment}", status_code=302)
        r.delete_cookie("sso_csrf")
        return r

    odoo_url = odoo_url.strip().rstrip("/")
    database = database.strip()
    username = username.strip()
    api_key  = api_key.strip()

    if not all([odoo_url, database, username, api_key]):
        return _error_redirect("missing_fields")

    # Retrieve the user's Bearer token captured during initiate and forward it
    # to the orchestrator — same token already used for all other BE API calls.
    entry = _sid_token_store.pop(sid, None)
    user_token = entry[0] if entry else None
    if not user_token:
        return _error_redirect("session_token_missing")

    orc_url = settings.ORCHESTRATOR_URL.rstrip("/")
    orc_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {user_token}",
    }
    async with httpx.AsyncClient(timeout=30) as http:
        try:
            verify_resp = await http.post(
                f"{orc_url}/shay/sales/odoo/verify",
                json={
                    "odoo_url":       odoo_url,
                    "database_name":  database,
                    "username":       username,
                    "api_key":        api_key,
                },
                headers=orc_headers,
            )
            verify_data = verify_resp.json()
        except Exception:
            return _error_redirect("orchestrator_unreachable")

    if verify_data.get("status") != "success":
        return _error_redirect(verify_data.get("message", "authentication_failed"))

    payload = {
        "odoo_url":  odoo_url,
        "database":  database,
        "username":  username,
        "api_key":   api_key,
        "auth_type": "api_key",
        "_sid":      sid,
    }
    odoo_data = _encode_payload(payload)

    response = RedirectResponse(
        url=f"{mcp_redirect_uri}#odoo_data={odoo_data}", status_code=302
    )
    response.delete_cookie("sso_csrf")
    return response
