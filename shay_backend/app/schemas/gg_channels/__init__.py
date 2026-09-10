"""
Channel-level GGMember / GGAppConnection schemas package (re-exports).

This package replaces the former single-file app/schemas/gg_channels.py,
split into member/app_connection modules to keep each file under the Raven
150-line style limit. All public names are re-exported here so existing
`from app.schemas.gg_channels import X` imports keep working unchanged.

The channel_id is always taken from the URL — the request body never
needs to repeat it. These schemas are narrower versions of the generic
member / app-connection schemas, scoped to channel operations only.
"""

from .member import (
    GGChannelMemberCreate,
    GGChannelMemberUpdate,
    GGChannelMemberResponse,
    GGChannelMemberList,
)
from .app_connection import (
    GGChannelAppConnectionCreate,
    GGChannelAppConnectionUpdate,
    GGChannelConnectorMetadata,
    GGChannelAppConnectionResponse,
    GGChannelAppConnectionList,
)

__all__ = [
    "GGChannelMemberCreate",
    "GGChannelMemberUpdate",
    "GGChannelMemberResponse",
    "GGChannelMemberList",
    "GGChannelAppConnectionCreate",
    "GGChannelAppConnectionUpdate",
    "GGChannelConnectorMetadata",
    "GGChannelAppConnectionResponse",
    "GGChannelAppConnectionList",
]
