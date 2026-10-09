"""The full attribute list of a catalog, kept per process for the required set's rule inputs.

Flag ``cpq_required_set_rules_read_all_attrs_enabled`` reads rule inputs from the full attribute list, which
``evaluate_rules_loop`` puts in the turn cache. The payload, summary and Beautify calls run ``auto_fill`` with their own
cache, so they never saw it and read the ~30 visible attributes instead: the Encryption Type rule fired in the loop and
was dropped again by the final call (ws 1267, APX 3000 and APX 900). This keeps the loop's latest full list per
(workspace, catalog prefix) so every caller reads the same one.
"""
from __future__ import annotations

import threading
from typing import Any

_LOCK = threading.Lock()
_FULL_ATTRS: dict[tuple[int | None, str], list[Any]] = {}


def remember_full_attrs(workspace_id: int | None, catalog_prefix: str, attrs: list[Any]) -> None:
    """Store the loop's full list (replaces the previous one for the same catalog)."""
    if attrs:
        with _LOCK:
            _FULL_ATTRS[(workspace_id, catalog_prefix)] = attrs


def full_attrs(workspace_id: int | None, catalog_prefix: str) -> list[Any] | None:
    """The latest full list stored for the catalog, or None when no loop has run for it in this process."""
    with _LOCK:
        return _FULL_ATTRS.get((workspace_id, catalog_prefix))


def _clear() -> None:
    """Tests only."""
    with _LOCK:
        _FULL_ATTRS.clear()
