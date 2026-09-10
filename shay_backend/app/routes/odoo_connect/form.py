"""
GET /connect/form — serve the multi-step Odoo credential HTML form.

Split from the original app/routes/odoo_connect.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
The HTML/CSS/JS template itself now lives in form_html.py (Wave B4 follow-up
split) so this file holds only the endpoint.
"""

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from app.services.sso_service import verify_state

from .form_html import FORM_HTML

router = APIRouter()


@router.get("/connect/form")
async def odoo_connect_form(state: str = Query(...)) -> HTMLResponse:
    """Serve the multi-step Odoo credential form."""
    try:
        verify_state(state, cookie_csrf=None)
    except Exception:
        return HTMLResponse(
            "<p style='font-family:sans-serif;padding:32px;color:#c00'>"
            "This link has expired or is invalid. Please start over from Claude.</p>",
            status_code=400,
        )
    return HTMLResponse(FORM_HTML.replace("__STATE__", state))
