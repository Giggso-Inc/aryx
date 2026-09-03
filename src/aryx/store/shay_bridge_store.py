"""Persistence helpers for Shay-to-Aryx workspace, datasource, and chat bridges.

As of the Raven Style Compliance Plan's Phase 2a (2026-09-03), `ShayBridgeStore`'s
methods live in 3 mixins — `store.shay_workspace_bridge`, `store.shay_chat_bridge`,
`store.shay_datasource_bridge` — since only one test file exercises this store
and it never patches an individual method (only `get_pool` for `__init__` and
`DatasourceStore` for `sync_datasource`, both retargeted/kept correctly). The
class itself stays importable at this exact path.
"""
from __future__ import annotations

from aryx.config import get_settings
from aryx.store.pool import get_pool
from aryx.store.shay_bridge_helpers import _aryx_workspace_name
from aryx.store.shay_chat_bridge import _ShayChatBridgeMixin
from aryx.store.shay_datasource_bridge import _ShayDatasourceBridgeMixin
from aryx.store.shay_workspace_bridge import _ShayWorkspaceBridgeMixin

__all__ = [
    "ShayBridgeStore",
    "_aryx_workspace_name",
    "get_shay_bridge_store",
]


class ShayBridgeStore(
    _ShayWorkspaceBridgeMixin,
    _ShayChatBridgeMixin,
    _ShayDatasourceBridgeMixin,
):
    """CRUD over Shay bridge tables backed by the Aryx Postgres."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool = get_pool(dsn)

    def close(self) -> None:
        """No-op: shared pool lifecycle is managed globally."""


def get_shay_bridge_store() -> ShayBridgeStore:
    """Return a store bound to the configured Aryx relational DSN."""
    return ShayBridgeStore(get_settings().effective_dsn())
