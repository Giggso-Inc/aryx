"""Decoded native-UI layout-export parsing: the depth-first component walk
and the cached, ``status=="Active"``-validated component list both display-
order maps build on (Phase 4 step 5 extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

``_walk_layout_components`` was a ``@staticmethod`` and needs nothing.
``_load_layout_components`` was a ``@classmethod`` that calls
``cls._walk_layout_components``, so it keeps an explicit ``cls`` first
parameter -- going through the class preserves any subclass override or test
patch of the walk. Engine-module globals go through the module object.
"""

from __future__ import annotations

import json
from typing import Any

from aryx.cpq import engine as _engine_module
from aryx.cpq.engine import logger
from aryx.cpq.layout_source import LayoutFileSource


def _walk_layout_components(node: Any) -> list[dict[str, Any]]:
    """Depth-first, document-order list of every leaf component object
    carrying a `resourceAttributeVarName` — the exact flattened order
    the native UI renders in, no `parent_id`/`order_number` tree walk
    needed (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md §1: the raw
    relational `order_number` is sibling-scoped, not a flat rank; this
    nested JSON's own array order already is one)."""
    out: list[dict[str, Any]] = []

    def _walk(n: Any) -> None:
        if isinstance(n, dict):
            if "resourceAttributeVarName" in n:
                out.append(n)
            for v in n.values():
                _walk(v)
        elif isinstance(n, list):
            for item in n:
                _walk(item)

    _walk(node)
    return out


def _load_layout_components(
    cls, workspace_id: int, catalog_prefix: str,
    layout_source: LayoutFileSource | None,
) -> list[dict[str, Any]] | None:
    """Parsed, `status=="Active"`-validated, flattened (document-order)
    component list for a catalog's layout export, or None if no
    currently-Active file exists. Cached process-lifetime — the shared
    parse step both `load_layout_display_order` (§2, visible-only) and
    `_load_layout_full_order` (§2b, ALL entries — rule conditions are
    frequently layout-*hidden*, e.g. a derived attr like Base Model,
    so the ranking those need can't come from the visible-only map)
    build on."""
    cache = _engine_module._LAYOUT_COMPONENTS_CACHE
    key = (workspace_id, catalog_prefix)
    if key in cache:
        return cache[key]
    source = layout_source or _engine_module._DEFAULT_LAYOUT_FILE_SOURCE
    text = source.get(catalog_prefix)
    if not text:
        cache[key] = None
        return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        logger.warning(
            "cpq layout: malformed layout JSON for catalog_prefix=%r",
            catalog_prefix, exc_info=True,
        )
        cache[key] = None
        return None
    if not isinstance(data, dict) or data.get("status") != "Active":
        logger.info(
            "cpq layout: layout file for %r has status=%r, not "
            "'Active' — ignoring (stale/deprecated export guard)",
            catalog_prefix,
            data.get("status") if isinstance(data, dict) else None,
        )
        cache[key] = None
        return None
    components = cls._walk_layout_components(data)
    cache[key] = components
    return components
