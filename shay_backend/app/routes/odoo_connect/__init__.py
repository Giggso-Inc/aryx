"""
Odoo Connect web form proxy — lets MCP route Odoo workspace connectivity
through a shay_backend-hosted form so credentials never pass through Claude chat.

Flow:
  1. MCP calls GET /api/v1/odoo/connect/initiate?sid=&redirect_uri=
     → shay_backend returns form_url pointing to the multi-step credential form.
  2. User opens form in browser:
       Step 1 — Enter Odoo URL  → POST /api/v1/odoo/connect/verify-url  → returns DB list.
       Step 2 — Pick database (auto-skipped if single).
       Step 3 — Enter username + API key → native form POST to /api/v1/odoo/connect/complete.
  3. shay_backend verifies credentials via orchestrator, then redirects to:
       {mcp_redirect_uri}#odoo_data=<base64url JSON>
  4. MCP's odoo_callback.html reads the fragment, POSTs tokens to /odoo/token.
  5. _odoo_complete picks up the payload and saves the connection.

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2): this used
to be a single 402-line app/routes/odoo_connect.py. It is now a package of
submodules by endpoint, combined into one `router` below so that
`from app.routes.odoo_connect import router` (used by main.py's route
registration) needs zero changes.

`_sid_token_store` is re-exported here too: tests/test_odoo_connect.py does
`from app.routes.odoo_connect import router, _sid_token_store` and mutates
it directly to seed/clear captured Bearer tokens. It is the *same* dict
object shared by every submodule (imported from .state), not a copy, so
mutating it through this re-export is visible to the endpoints.

Route registration order matches the original file's declaration order:
initiate, form, verify-url, complete. There is no path-collision risk here
since every path is a distinct literal segment under /connect/.
"""

from fastapi import APIRouter

from . import complete
from . import form
from . import initiate
from . import verify
from .state import _sid_token_store

router = APIRouter(tags=["Odoo Connect"])
router.include_router(initiate.router)
router.include_router(form.router)
router.include_router(verify.router)
router.include_router(complete.router)

__all__ = ["router", "_sid_token_store"]
