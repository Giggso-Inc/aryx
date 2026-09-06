"""
SSO login routes for Google/Microsoft OAuth2 sign-in and sign-up.

Split from a single 233-line module into this package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5 — the final wave of
the full sweep) — one submodule per endpoint, combined here into a single
`router` in the original endpoint order so route precedence and external
behavior (app/routes/__init__.py's `from app.routes.sso import router`
re-export) are unchanged.
"""

from fastapi import APIRouter

from app.routes.sso import initiate
from app.routes.sso import callback

router = APIRouter(tags=["SSO"])

# Preserve original registration order: sso_initiate, sso_callback
router.include_router(initiate.router)
router.include_router(callback.router)
