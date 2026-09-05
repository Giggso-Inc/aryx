"""
Notification routes: realtime notification preferences + email notification
settings (mounted at /api/v1/notifications).

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2 / wave B):
this used to be a single 768-line app/routes/notifications.py. It is now a
package split one-endpoint-per-file (realtime settings: get/save/update;
email settings: save/update/get/trigger, plus a small email_helpers.py for
the shared VALID_ROUTINES constant), combined into one `router` below so
that `from app.routes.notifications import router` (used by
app/routes/__init__.py's route registration) needs zero changes.

Route registration order is not load-bearing here: none of the
submodules' path templates collide (every path is either a distinct
literal segment or scoped under a different literal prefix), so the
submodules are combined in any order.
"""

from fastapi import APIRouter

from . import email_get
from . import email_save
from . import email_trigger
from . import email_update
from . import get_settings
from . import save_settings
from . import update_settings

router = APIRouter()
router.include_router(get_settings.router)
router.include_router(save_settings.router)
router.include_router(update_settings.router)
router.include_router(email_save.router)
router.include_router(email_update.router)
router.include_router(email_get.router)
router.include_router(email_trigger.router)

__all__ = ["router"]
