"""
Audit log list/filter API. Returns audit entries scoped to the current user's company.

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5): this used to be a
single 389-line app/routes/audit.py. It is now a package of submodules by
endpoint (list_all, channel, thread), plus shared models.py/helpers.py,
combined into one `router` below so that `from app.routes import audit`
(used by app/core/app_routers.py as `audit.router`) needs zero changes.

Route registration order matches the original file's declaration order:
GET "" (list_audit_log), GET /channel/{channel_id} (list_channel_audit_log),
GET /channel/{channel_id}/thread/{thread_id} (list_thread_audit_log). The
literal segment "channel" in the second and third routes never collides
with a dynamic path here (there is no bare `/{something}` route in this
router), so registration order has no routing-behavior effect — it is
preserved anyway per the wave B5 plan.
"""

from fastapi import APIRouter

from . import list_all
from . import channel
from . import thread
from .helpers import (
    _audit_query,
    _get_user_names,
    _get_related_user_ids_for_audit_rows,
    _collect_user_names_for_rows,
    _rows_to_items,
)
from .models import AuditLogEntry, AuditLogListResponse

router = APIRouter()
# list_all.router's only route is registered at the literal empty path ""
# (mirroring the original file's `@router.get("", ...)`). FastAPI's
# `include_router` refuses to combine an empty-path route with an empty
# prefix ("Prefix and path cannot be both empty") even though the final
# mount always supplies a real prefix (see app/core/app_routers.py:
# `app.include_router(audit.router, prefix="/api/v1/audit-log", ...)`) —
# the check fires at this intermediate aggregation step regardless. Merging
# the routes list directly sidesteps that intermediate-only restriction
# without changing the resulting path (using "/" instead of "" here would
# add an unwanted trailing slash to the final mounted URL).
router.routes.extend(list_all.router.routes)
router.include_router(channel.router)
router.include_router(thread.router)

__all__ = [
    "router",
    "AuditLogEntry",
    "AuditLogListResponse",
    "_audit_query",
    "_get_user_names",
    "_get_related_user_ids_for_audit_rows",
    "_collect_user_names_for_rows",
    "_rows_to_items",
]
