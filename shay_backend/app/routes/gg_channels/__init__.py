"""
GG Channel routes — channel-level GGMember and GGAppConnection management.

Separate from the main channels.py router (which handles channel CRUD).
Mounted at: /api/v1/gg-channels

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2): this used
to be a single 450-line app/routes/gg_channels.py. It is now a package of
submodules by resource, combined into one `router` below so that
`from .gg_channels import router` (used by app/routes/__init__.py's
`gg_channels_router`) needs zero changes.

Endpoints
─────────
  Members (gg_members, level='channel')            — see members.py
    GET    /{channel_id}/members
    POST   /{channel_id}/members
    PUT    /{channel_id}/members/{user_id}
    DELETE /{channel_id}/members/{user_id}

  App Connections (gg_app_connections, level='channel') — see connections.py
    GET    /{channel_id}/app-connections
    POST   /{channel_id}/app-connections
    PUT    /{channel_id}/app-connections/{connection_id}
    DELETE /{channel_id}/app-connections/{connection_id}

Registration order matches the original file exactly (members before
connections) — there is no dynamic-vs-literal path collision risk here
since every path in both submodules starts with the same dynamic
`/{channel_id}` prefix followed by a distinct literal segment
(`/members` vs `/app-connections`), so ordering between the two submodules
does not change route matching, but is preserved anyway for fidelity.
"""

from fastapi import APIRouter

from . import connections
from . import members
from .helpers import _get_channel_or_404, _member_resp, _conn_resp, _to_uuid

router = APIRouter()
router.include_router(members.router)
router.include_router(connections.router)

__all__ = ["router"]
