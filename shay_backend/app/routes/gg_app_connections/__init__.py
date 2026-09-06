"""
GGAppConnection routes — unified app connections across workspace / channel / thread scopes.

Access control
──────────────
  • CREATE  : user must be an active GGMember at the target scope (or company admin).
  • READ    : user must be an active GGMember at the target scope, or belong to the
              same company as the workspace/channel.
  • UPDATE / DELETE : user must be the original connector OR an admin member at scope.

Scope resolution for GET /resolved follows: thread → channel → workspace (most specific wins).

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 and Wave B4): this
used to be a single 687-line app/routes/gg_app_connections.py, later split
into a package of larger submodules (collection.py, detail.py, _shared.py)
that themselves grew past the 150-line limit. Each is now split further,
one endpoint (or helper cluster) per file, combined into one `router` below
so that `from app.routes.gg_app_connections import router` (used by
app/routes/__init__.py's route registration) needs zero changes.

Route registration ORDER matters here: FastAPI/Starlette matches routes in
registration order for a given HTTP method, and a single-segment dynamic
path like GET /{connection_id} would otherwise swallow the literal
single-segment path GET /resolved. resolved.py, create.py, and list.py
(formerly collection.py — owning /resolved, POST /, and GET / respectively)
are therefore included BEFORE get_connection.py, update_connection.py, and
delete_connection.py (formerly detail.py — owning the dynamic
/{connection_id} routes), preserving the original files' endpoint
declaration order exactly. scope.py's /scope/{scope_type}/{scope_id} is a
two-segment path with no collision risk against the single-segment routes,
so its position relative to the others is not load-bearing.
"""

from fastapi import APIRouter

from . import create
from . import delete_connection
from . import get_connection
from . import list as list_
from . import resolved
from . import scope
from . import update_connection
from ._shared import assert_member_access, assert_scope_exists, build_response

router = APIRouter()
router.include_router(resolved.router)
router.include_router(create.router)
router.include_router(list_.router)
router.include_router(get_connection.router)
router.include_router(update_connection.router)
router.include_router(delete_connection.router)
router.include_router(scope.router)

__all__ = ["router", "assert_member_access", "assert_scope_exists", "build_response"]
