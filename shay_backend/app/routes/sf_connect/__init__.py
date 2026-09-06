"""
Salesforce Connect OAuth proxy — lets MCP route Salesforce workspace connectivity
through shay_backend's registered Salesforce Connected App.

Uses PKCE (S256): the code_verifier is embedded inside the HMAC-signed state so
no server-side storage is needed for the verifier.

Flow:
  1. MCP calls GET /api/v1/sf/connect/initiate?sid=<session_id>&redirect_uri=<mcp_callback>
     → shay_backend generates PKCE pair, embeds code_verifier in signed state,
       builds Salesforce auth URL and returns it.
  2. User completes consent in browser.
  3. Salesforce redirects to shay_backend GET /api/v1/sf/connect/callback?code=&state=
     → shay_backend extracts code_verifier from state, exchanges the code,
       fetches the Salesforce user profile, encodes tokens as base64url JSON,
       and redirects to {mcp_redirect_uri}#sf_data=<base64>
  4. MCP's salesforce_callback.html reads the fragment, POSTs tokens to /salesforce/token.

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md): this used to be a single
245-line app/routes/sf_connect.py. It is now a package of submodules,
combined into one `router` below so that
`from app.routes.sf_connect import router` (used by
app/core/app_routers.py's route registration) needs zero changes.

Route registration order matches the original file's declaration order:
initiate, callback. Both are distinct literal path segments under
/connect/, so there is no path-collision risk.
"""

from fastapi import APIRouter

from . import callback
from . import initiate

router = APIRouter(tags=["Salesforce Connect"])
router.include_router(initiate.router)
router.include_router(callback.router)

__all__ = ["router"]
