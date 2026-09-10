"""
Subscription routes for CRUD operations and company plan management

Author: Pranhav Vimalbalaji
Date: 2025-01-27
Version: 1.0.0

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2): this used
to be a single 529-line app/routes/subscriptions.py. It is now a package of
submodules by resource, combined into one `router` below so that
`from app.routes.subscriptions import router` / `subscriptions.router`
(used by main.py's route registration) needs zero changes.

Route registration order matches the original file's declaration order:
create (POST /), list (GET /), get/update/delete (`/{subscription_id}`),
then the company-current-plan endpoints (`/company/my/current-plan` and
`/company/{company_id}/current-plan`). There is no path-collision risk
against `/{subscription_id}` here (unlike the channels split) since the
company-plan paths have 3 segments. Within the company-plan pair though,
company_plan_mine.py's literal `/company/my/current-plan` MUST be
registered before company_plan_by_id.py's dynamic
`/company/{company_id}/current-plan` (Wave B4 split of the former single
company_plan.py module), or "my" would be captured as a company_id.
"""

from fastapi import APIRouter

from . import company_plan_by_id
from . import company_plan_mine
from . import create
from . import list_subscriptions
from . import detail
from .helpers import validate_uuid

router = APIRouter()
router.include_router(create.router)
router.include_router(list_subscriptions.router)
router.include_router(detail.router)
router.include_router(company_plan_mine.router)
router.include_router(company_plan_by_id.router)

__all__ = ["router", "validate_uuid"]
