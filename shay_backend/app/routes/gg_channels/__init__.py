"""
GG Channel routes — channel-level GGMember and GGAppConnection management.

Separate from the main channels.py router (which handles channel CRUD).
Mounted at: /api/v1/gg-channels

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2 and Wave
B4): this used to be a single 450-line app/routes/gg_channels.py, later
split into connections.py and members.py which themselves grew past the
150-line limit. Each is now split further, one endpoint per file, combined
into one `router` below so that `from .gg_channels import router` (used by
app/routes/__init__.py's `gg_channels_router`) needs zero changes.

Endpoints
─────────
  Members (gg_members, level='channel')
    GET    /{channel_id}/members                          — mem_list.py
    POST   /{channel_id}/members                           — mem_add.py
    PUT    /{channel_id}/members/{user_id}                  — mem_update.py
    DELETE /{channel_id}/members/{user_id}                  — mem_remove.py

  App Connections (gg_app_connections, level='channel')
    GET    /{channel_id}/app-connections                    — conn_list.py
    POST   /{channel_id}/app-connections                    — conn_connect.py
    PUT    /{channel_id}/app-connections/{connection_id}    — conn_update.py
    DELETE /{channel_id}/app-connections/{connection_id}    — conn_disconnect.py

Registration order matches the original file exactly (members before
connections, and list/add/update/remove or list/connect/update/disconnect
within each) — there is no dynamic-vs-literal path collision risk here
since every path starts with the same dynamic `/{channel_id}` prefix
followed by a distinct literal segment (`/members` vs `/app-connections`),
so ordering does not change route matching, but is preserved anyway for
fidelity.
"""

from fastapi import APIRouter

from . import conn_connect
from . import conn_disconnect
from . import conn_list
from . import conn_update
from . import mem_add
from . import mem_list
from . import mem_remove
from . import mem_update
from .helpers import _get_channel_or_404, _member_resp, _conn_resp, _to_uuid

router = APIRouter()
router.include_router(mem_list.router)
router.include_router(mem_add.router)
router.include_router(mem_update.router)
router.include_router(mem_remove.router)
router.include_router(conn_list.router)
router.include_router(conn_connect.router)
router.include_router(conn_update.router)
router.include_router(conn_disconnect.router)

__all__ = ["router"]
