"""
Gmail Connect OAuth proxy — lets MCP route Gmail workspace connectivity
through shay_backend's already-registered Google OAuth client.

Flow:
  1. MCP calls GET /api/v1/gmail/connect/initiate?sid=<session_id>&redirect_uri=<mcp_gmail_callback>
     → shay_backend builds Google auth URL with Gmail scopes and returns it.
  2. User completes consent in browser.
  3. Google redirects to shay_backend GET /api/v1/gmail/connect/callback?code=&state=
     → shay_backend exchanges the code, fetches the user email, encodes the
       Google tokens as base64url JSON, and redirects to:
       {mcp_redirect_uri}#gmail_data=<base64>
  4. MCP's gmail_callback.html reads the fragment, POSTs tokens to /gmail/token.

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md): this used to be a single
181-line app/routes/gmail_connect.py. It is now a package of submodules by
endpoint, combined into one `router` below so that
`from app.routes.gmail_connect import router` (used by
app/core/app_routers.py's route registration) needs zero changes.

Route registration order matches the original file's declaration order:
initiate, callback. Both are distinct literal path segments under
/connect/, so there is no path-collision risk.
"""

from fastapi import APIRouter

from . import callback
from . import initiate

router = APIRouter(tags=["Gmail Connect"])
router.include_router(initiate.router)
router.include_router(callback.router)

__all__ = ["router"]
