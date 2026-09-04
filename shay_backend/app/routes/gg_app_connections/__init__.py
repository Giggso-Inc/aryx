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
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5): this used to be a
single 687-line app/routes/gg_app_connections.py. It is now a package of
submodules by resource/sub-area, combined into one `router` below so that
`from app.routes.gg_app_connections import router` (used by
app/routes/__init__.py's route registration) needs zero changes.

Route registration ORDER matters here: FastAPI/Starlette matches routes in
registration order for a given HTTP method, and a single-segment dynamic
path like GET /{connection_id} would otherwise swallow the literal
single-segment path GET /resolved. collection.py (which owns /resolved,
plus POST / and GET /) is therefore included BEFORE detail.py (which owns
the dynamic /{connection_id} routes), preserving the original file's
endpoint declaration order exactly. scope.py's /scope/{scope_type}/{scope_id}
is a two-segment path with no collision risk against the single-segment
routes, so its position relative to the others is not load-bearing.
"""

from fastapi import APIRouter

from . import collection
from . import detail
from . import scope
from ._shared import assert_member_access, assert_scope_exists, build_response

router = APIRouter()
router.include_router(collection.router)
router.include_router(detail.router)
router.include_router(scope.router)

__all__ = ["router", "assert_member_access", "assert_scope_exists", "build_response"]
