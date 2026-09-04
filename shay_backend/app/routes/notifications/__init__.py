"""
Notification routes: realtime notification preferences + email notification
settings (mounted at /api/v1/notifications).

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2): this used
to be a single 768-line app/routes/notifications.py. It is now a package
split by resource area (realtime vs. email settings), combined into one
`router` below so that `from app.routes.notifications import router`
(used by app/routes/__init__.py's route registration) needs zero changes.

Route registration order is not load-bearing here: none of the two
submodules' path templates collide (every path is either a distinct
literal segment or scoped under a different literal prefix), so
`realtime` and `email_settings` are combined in either order.
"""

from fastapi import APIRouter

from . import email_settings
from . import realtime

router = APIRouter()
router.include_router(realtime.router)
router.include_router(email_settings.router)

__all__ = ["router"]
