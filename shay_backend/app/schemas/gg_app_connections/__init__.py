"""
GGAppConnection schemas package (re-exports).

This package replaces the former single-file app/schemas/gg_app_connections.py,
split into create_update/responses modules to keep each file under the
Raven 150-line style limit. All public names are re-exported here so
existing `from app.schemas.gg_app_connections import X` imports keep
working unchanged.

Unified app connections across workspace / channel / thread scopes.
"""

from .create_update import ScopeLevel, GGAppConnectionCreate, GGAppConnectionUpdate
from .responses import ConnectorMetadata, GGAppConnectionResponse, GGAppConnectionList

__all__ = [
    "ScopeLevel",
    "GGAppConnectionCreate",
    "GGAppConnectionUpdate",
    "ConnectorMetadata",
    "GGAppConnectionResponse",
    "GGAppConnectionList",
]
