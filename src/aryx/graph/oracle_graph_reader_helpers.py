"""Row-mapping helpers for the Oracle Property Graph reader.

Split out of `graph/oracle_graph_reader.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

import json
from typing import Any


def _parse_attrs(raw: Any) -> dict[str, Any]:
    """Best-effort decode of the stored attributes column.

    python-oracledb can return a native JSON column as an already-parsed
    dict or as a string depending on driver/version — handle both rather
    than assume.
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _entity(row: tuple[Any, ...]) -> dict[str, Any]:
    """Map an (entity_id, type, name[, attributes]) row to an entity dict."""
    entity: dict[str, Any] = {"id": row[0], "type": row[1], "name": row[2]}
    if len(row) > 3:
        entity["attributes"] = _parse_attrs(row[3])
    return entity
