"""
Subscription Plans routes for CRUD operations

Author: Pranhav Vimalbalaji
Date: 2025-01-27
Version: 1.0.0

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5): this used to be a
single 327-line app/routes/subscription_plans.py. It is now a package of
submodules by resource (create, list_plans, detail, active), combined into
one `router` below so that `from app.routes import subscription_plans`
(used by app/core/app_routers.py as `subscription_plans.router`) needs zero
changes.

Route registration order matches the original file's declaration order:
create (POST /), list (GET /), get/update/delete (`/{plan_id}` — combined
into one detail.py module since they share the same path and per-method
handlers), then `/active/plans`. Note `/active/plans` is declared (in file
order) AFTER the dynamic `/{plan_id}` route both here and in the original
file — this is safe because `/active/plans` has two path segments while
`/{plan_id}` has one, so FastAPI/Starlette never mis-routes a GET
"/active/plans" request to the `{plan_id}` handler (unlike the
`/company/my/current-plan` vs `/company/{company_id}/current-plan` case in
the subscriptions split, which does require ordering). Registration order
is preserved anyway per the wave B5 plan.
"""

from fastapi import APIRouter

from . import create
from . import list_plans
from . import detail
from . import active
from .helpers import validate_uuid

router = APIRouter()
router.include_router(create.router)
router.include_router(list_plans.router)
router.include_router(detail.router)
router.include_router(active.router)

__all__ = ["router", "validate_uuid"]
