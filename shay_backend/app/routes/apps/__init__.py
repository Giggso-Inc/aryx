"""
App routes for CRUD operations to manage available applications

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2): this used
to be a single 453-line app/routes/apps.py. It is now a package of
submodules by resource/sub-area, combined into one `router` below so that
`from .apps import router` (used by app/routes/__init__.py's
`apps_router`) needs zero changes.

Route registration ORDER matters here: FastAPI/Starlette matches routes in
registration order for a given HTTP method, and a single-segment dynamic
path like GET /{app_id} would otherwise swallow literal single-segment
paths such as GET /categories or GET /stats. The static-path submodules
(create, list_apps, categories_stats) are therefore included BEFORE the
dynamic-path submodule (detail), preserving the original file's endpoint
declaration order exactly.
"""

from fastapi import APIRouter

from . import create
from . import list_apps
from . import categories_stats
from . import detail
from .common import security, CLOUD_DRIVE_APP_KEYS, EXCLUDED_APP_KEYS

router = APIRouter()
router.include_router(create.router)
router.include_router(list_apps.router)
router.include_router(categories_stats.router)
router.include_router(detail.router)

__all__ = ["router", "security", "CLOUD_DRIVE_APP_KEYS", "EXCLUDED_APP_KEYS"]
