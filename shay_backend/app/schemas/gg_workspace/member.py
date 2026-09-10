"""
Workspace-scoped GGMember schemas.

Split out of the former app/schemas/gg_workspace.py to keep each file
under the Raven 150-line style limit. See
app/schemas/gg_workspace/__init__.py for the full package layout.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class GGWorkspaceMemberCreate(BaseModel):
    """Body for adding a member at workspace scope."""

    user_id:     UUID
    role:        str                       = Field("member", description="member | admin | viewer")
    permissions: Optional[Dict[str, Any]] = None
    invited_by:  Optional[UUID]           = None


class GGWorkspaceMemberUpdate(BaseModel):
    """Body for updating an existing workspace membership."""

    role:        Optional[str]             = None
    is_active:   Optional[bool]            = None
    permissions: Optional[Dict[str, Any]] = None


class GGWorkspaceMemberResponse(BaseModel):
    """Response for a single workspace GGMember."""

    id:           str
    user_id:      str
    workspace_id: str
    level:        str = "workspace"
    role:         str
    is_active:    bool
    permissions:  Optional[Dict[str, Any]] = None
    invited_by:   Optional[str]            = None
    joined_at:    Optional[datetime]       = None
    created_at:   Optional[datetime]       = None
    updated_at:   Optional[datetime]       = None
    name:         Optional[str]            = None
    email:        Optional[str]            = None

    class Config:
        from_attributes = True


class GGWorkspaceMemberList(BaseModel):
    """Paginated list of workspace GGMembers."""

    members: List[GGWorkspaceMemberResponse]
    total:   int
    page:    int
    size:    int
    pages:   int
