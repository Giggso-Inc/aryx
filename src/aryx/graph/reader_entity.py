"""Entity-row mapping shared by GraphReader and its subgraph builder.

Split out of `graph/reader.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

import json
from typing import Any

# Node properties written by the projection itself, not entity attributes.
_INTERNAL_PROPS = frozenset({"id", "type", "name", "iri"})


def _parse_attrs(raw: Any) -> dict[str, Any]:
    """Extract entity attributes from a node's property map.

    Current graphs store attributes as individual native node properties, so
    ``raw`` is the properties() map minus the internal projection fields.
    Graphs projected before the native-property lift carry a single
    stringified JSON blob under ``attrs`` — decode and merge it so reads work
    against both generations without a reprojection.
    """
    if not raw:
        return {}
    if isinstance(raw, str):  # legacy: bare attrs blob
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}
    if isinstance(raw, dict):
        attrs: dict[str, Any] = {}
        for k, v in raw.items():
            if k in _INTERNAL_PROPS or k == "attrs":
                continue
            # Source attrs whose names collide with projection fields are
            # written as src_id / src_name / ... — map them back so callers
            # see the original attribute names.
            if k.startswith("src_") and k[4:] in _INTERNAL_PROPS:
                attrs.setdefault(k[4:], v)
            else:
                attrs[k] = v
        legacy = raw.get("attrs")
        if isinstance(legacy, str) and legacy:
            try:
                attrs = {**json.loads(legacy), **attrs}
            except (TypeError, ValueError):
                pass
        return attrs
    return {}


def _entity(row: list[Any]) -> dict[str, Any]:
    """Map an (id, type, name[, attrs]) result row to an entity dict."""
    entity: dict[str, Any] = {"id": row[0], "type": row[1], "name": row[2]}
    if len(row) > 3:
        entity["attributes"] = _parse_attrs(row[3])
    return entity
