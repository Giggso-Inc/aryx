"""
Channel-scoped GGMember schemas.

Split out of the former app/schemas/gg_channels.py to keep each file
under the Raven 150-line style limit. See
app/schemas/gg_channels/__init__.py for the full package layout.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class GGChannelMemberCreate(BaseModel):
    """Body for adding a member at channel scope."""

    user_id:     UUID
    role:        str                       = Field("member", description="member | admin | viewer")
    permissions: Optional[Dict[str, Any]] = None
    invited_by:  Optional[UUID]           = None


class GGChannelMemberUpdate(BaseModel):
    """Body for updating an existing channel membership."""

    role:        Optional[str]             = None
    is_active:   Optional[bool]            = None
    permissions: Optional[Dict[str, Any]] = None


class GGChannelMemberResponse(BaseModel):
    """Response for a single channel GGMember."""

    id:          str
    user_id:     str
    channel_id:  str
    level:       str = "channel"
    role:        str
    is_active:   bool
    permissions: Optional[Dict[str, Any]] = None
    invited_by:  Optional[str]            = None
    joined_at:   Optional[datetime]       = None
    created_at:  Optional[datetime]       = None
    updated_at:  Optional[datetime]       = None

    class Config:
        from_attributes = True


class GGChannelMemberList(BaseModel):
    """Paginated list of channel GGMembers."""

    members: List[GGChannelMemberResponse]
    total:   int
    page:    int
    size:    int
    pages:   int
