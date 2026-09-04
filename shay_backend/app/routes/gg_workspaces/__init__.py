"""
GG Workspace routes — workspace-level GGMember and GGAppConnection management.

Separate from the main workspaces.py router (which handles workspace CRUD).
Mounted at: /api/v1/gg-workspaces

Endpoints
─────────
  Members (gg_members, level='workspace')
    GET    /{workspace_id}/members
    POST   /{workspace_id}/members
    PUT    /{workspace_id}/members/{user_id}
    DELETE /{workspace_id}/members/{user_id}
    GET    /{workspace_id}/members/{user_id}/effective-role

  App Connections (gg_app_connections, level='workspace')
    GET    /{workspace_id}/app-connections
    POST   /{workspace_id}/app-connections
    PUT    /{workspace_id}/app-connections/{connection_id}
    DELETE /{workspace_id}/app-connections/{connection_id}

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2): this used
to be a single 635-line app/routes/gg_workspaces.py. It is now a package of
submodules by resource (members, app_connections), combined into one
`router` below so that `from app.routes.gg_workspaces import router` needs
zero changes.

Both sub-areas use disjoint path prefixes (/members... vs
/app-connections...), so registration order between them doesn't affect
route matching; members is still included first to preserve the original
file's declaration order.
"""

from fastapi import APIRouter

from . import members
from . import app_connections
from .helpers import _get_workspace_or_404, _member_resp, _conn_resp, _to_uuid

router = APIRouter()
router.include_router(members.router)
router.include_router(app_connections.router)

__all__ = ["router"]
