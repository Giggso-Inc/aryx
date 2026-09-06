"""Workspace routes for CRUD operations.

Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2): this used
to be a single 548-line app/routes/workspaces.py. It is now a package of
submodules by operation, combined into one `router` below so that
`from app.routes.workspaces import router` needs zero changes.

`_aryx_headers` and `_get_workspace_or_404` are re-exported here because two
other modules import them directly from this flat path: app/routes/aryx.py
and app/routes/datasources/upload.py (confirmed via
`grep -rn "from app.routes.workspaces import"`).

Route registration ORDER matters here: FastAPI/Starlette matches routes in
registration order for a given HTTP method, and a single-segment dynamic
path like GET /{workspace_id} would otherwise swallow the literal
single-segment path POST /. list_get (which owns both GET / and GET
/{workspace_id}) preserves the original file's internal ordering by
declaring GET / before GET /{workspace_id} in the same module; create
(POST /) and the /{workspace_id}/* submodules don't collide with each
other by method or path shape, so cross-module include order only needs
to keep create/list_get ahead of the dynamic-path submodules to match the
original file's endpoint declaration order exactly. (delete.py and
purge.py were originally one delete_purge.py module, further split in
Wave B4; DELETE /{workspace_id} and POST /{workspace_id}/purge differ by
method/path shape so their relative order isn't load-bearing either.)
"""

from fastapi import APIRouter

from . import create
from . import list_get
from . import update
from . import delete
from . import purge
from . import stats
from .helpers import _aryx_headers, _get_workspace_or_404

router = APIRouter()
router.include_router(create.router)
router.include_router(list_get.router)
router.include_router(update.router)
router.include_router(delete.router)
router.include_router(purge.router)
router.include_router(stats.router)

__all__ = ["router", "_aryx_headers", "_get_workspace_or_404"]
