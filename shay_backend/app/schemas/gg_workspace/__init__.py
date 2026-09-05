"""
Workspace-level GGMember / GGAppConnection schemas package (re-exports).

This package replaces the former single-file app/schemas/gg_workspace.py,
split into member/app_connection modules to keep each file under the Raven
150-line style limit. All public names are re-exported here so existing
`from app.schemas.gg_workspace import X` imports keep working unchanged.

The workspace_id is always taken from the URL — the request body never
needs to repeat it. These schemas are narrower versions of the generic
member / app-connection schemas, scoped to workspace operations only.
"""

from .member import (
    GGWorkspaceMemberCreate,
    GGWorkspaceMemberUpdate,
    GGWorkspaceMemberResponse,
    GGWorkspaceMemberList,
)
from .app_connection import (
    GGWorkspaceAppConnectionCreate,
    GGWorkspaceAppConnectionUpdate,
    GGWorkspaceConnectorMetadata,
    GGWorkspaceAppConnectionResponse,
    GGWorkspaceAppConnectionList,
)

__all__ = [
    "GGWorkspaceMemberCreate",
    "GGWorkspaceMemberUpdate",
    "GGWorkspaceMemberResponse",
    "GGWorkspaceMemberList",
    "GGWorkspaceAppConnectionCreate",
    "GGWorkspaceAppConnectionUpdate",
    "GGWorkspaceConnectorMetadata",
    "GGWorkspaceAppConnectionResponse",
    "GGWorkspaceAppConnectionList",
]
