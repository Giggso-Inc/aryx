"""
AppAccount routes for managing app connections to channels

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2): this used
to be a single 755-line app/routes/app_accounts.py. It is now a package of
submodules by endpoint, combined into one `router` below so that
`from app.routes import app_accounts` / `app_accounts_router` (used by
main.py's route registration) needs zero changes.

Route registration ORDER matters here: GET /stats is a literal path that
must be registered before the dynamic GET /{app_account_id} in detail.py, or
a request for /stats would be swallowed by the {app_account_id} path
parameter. create, list, and connect are all registered on distinct literal
paths ("/" and "/connect") with no collision risk against each other or
against stats/detail/mutate, so their relative order is preserved as a
courtesy to match the original file's declaration order, not because it is
load-bearing.
"""

from fastapi import APIRouter

from . import create
from . import list as list_
from . import stats
from . import detail
from . import mutate
from . import connect

router = APIRouter()
router.include_router(create.router)
router.include_router(list_.router)
router.include_router(stats.router)
router.include_router(detail.router)
router.include_router(mutate.router)
router.include_router(connect.router)

__all__ = ["router"]
