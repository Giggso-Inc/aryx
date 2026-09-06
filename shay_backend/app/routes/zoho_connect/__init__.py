"""
Zoho CRM Connect OAuth proxy — lets MCP route Zoho workspace connectivity
through shay_backend's registered Zoho Connected App.

Flow:
  1. MCP calls GET /api/v1/zoho/connect/initiate?sid=<session_id>&redirect_uri=<mcp_callback>
     → shay_backend builds Zoho auth URL with CRM scopes and returns it.
  2. User completes consent in browser.
  3. Zoho redirects to shay_backend GET /api/v1/zoho/connect/callback?code=&state=&accounts-server=
     → shay_backend exchanges the code, fetches the Zoho user profile, encodes the
       tokens as base64url JSON, and redirects to:
       {mcp_redirect_uri}#zoho_data=<base64>
  4. MCP's zoho_callback.html reads the fragment, POSTs tokens to /zoho/token.

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md): this used to be a single
209-line app/routes/zoho_connect.py. It is now a package of submodules by
endpoint, combined into one `router` below so that
`from app.routes.zoho_connect import router` (used by
app/core/app_routers.py's route registration) needs zero changes.

Route registration order matches the original file's declaration order:
initiate, callback. Both are distinct literal path segments under
/connect/, so there is no path-collision risk.
"""

from fastapi import APIRouter

from . import callback
from . import initiate

router = APIRouter(tags=["Zoho Connect"])
router.include_router(initiate.router)
router.include_router(callback.router)

__all__ = ["router"]
