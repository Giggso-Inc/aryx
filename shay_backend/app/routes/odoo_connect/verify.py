"""
POST /connect/verify-url — validate the Odoo URL (AJAX) and return the list
of available databases.

Split from the original app/routes/odoo_connect.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.services.sso_service import verify_state

from .state import _prune_token_store, _sid_token_store

router = APIRouter()


@router.post("/connect/verify-url")
async def odoo_connect_verify_url(request: Request) -> JSONResponse:
    """Validate the Odoo URL and return available databases."""
    _prune_token_store()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    state = body.get("state", "")
    odoo_url = (body.get("odoo_url") or "").strip().rstrip("/")

    cookie_csrf = request.cookies.get("sso_csrf")
    try:
        state_data = verify_state(state, cookie_csrf=cookie_csrf)
    except Exception:
        return JSONResponse({"error": "invalid_state"}, status_code=400)

    if not odoo_url.startswith(("https://", "http://")):
        return JSONResponse(
            {"error": "URL must start with https:// or http://"}, status_code=400
        )

    sid = state_data.get("invite_id", "")
    entry = _sid_token_store.get(sid)
    if not entry:
        return JSONResponse({"error": "session_token_missing"}, status_code=401)

    orc_url = settings.ORCHESTRATOR_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=30) as http:
        try:
            resp = await http.post(
                f"{orc_url}/shay/sales/verify_odoo_url",
                json={"odoo_url": odoo_url},
                headers={"Authorization": f"Bearer {entry[0]}"},
            )
            data = resp.json()
        except Exception as exc:
            return JSONResponse(
                {"error": f"Could not reach Odoo — check the URL. ({exc})"}, status_code=502
            )

    if data.get("status") != "success":
        return JSONResponse(
            {"error": data.get("message", "Odoo instance unreachable")}, status_code=400
        )

    databases: list = data.get("data") or []
    if not databases:
        return JSONResponse(
            {"error": "No databases found on this Odoo instance."}, status_code=400
        )

    return JSONResponse({"databases": databases, "base_url": odoo_url})
