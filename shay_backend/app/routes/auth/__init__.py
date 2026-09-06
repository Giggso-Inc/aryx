"""
Authentication routes for OAuth2 login and JWT token management.

Split from a single 312-line module into this package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5 — the final wave of
the full sweep) — one submodule per endpoint, combined here into a single
`router` in the original endpoint order so route precedence and external
behavior (app/routes/__init__.py's `from app.routes.auth import router`
re-export) are unchanged.
"""

from fastapi import APIRouter

from app.routes.auth import login
from app.routes.auth import callback
from app.routes.auth import refresh
from app.routes.auth import get_me
from app.routes.auth import logout
from app.routes.auth import update_me
from app.routes.auth import dev_token

router = APIRouter()

# Preserve original registration order:
# login, oauth_callback, refresh_token, get_current_user_info (GET /me),
# logout, update_current_user (PUT /me), get_dev_token
router.include_router(login.router)
router.include_router(callback.router)
router.include_router(refresh.router)
router.include_router(get_me.router)
router.include_router(logout.router)
router.include_router(update_me.router)
router.include_router(dev_token.router)
