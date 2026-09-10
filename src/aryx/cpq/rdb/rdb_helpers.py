"""Value-coercion + pattern helpers shared by the Postgres and Oracle CPQ RDB
accessors.

Split out of `cpq/rdb.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

import json
from typing import Any


def _as_int(val: Any) -> int | None:
    """Coerce a JSON-extracted value to int, or None."""
    try:
        return int(str(val).strip())
    except (TypeError, ValueError):
        return None


def _as_attrs(raw: Any) -> dict[str, Any]:
    """Coerce a JSON/JSONB column value to a dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (str, bytes)):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}
    return {}


def _type_pattern(catalog_prefix: str, suffix: str) -> str:
    """Normalized-ontology-type LIKE pattern for a rule/function query.

    suffix is the lowercase, no-underscore tag stem (e.g. "bmconfigrule").
    catalog_prefix, when set, restricts the match to ontology types from one
    ingested source (see CpqEngine._catalog_prefix) — needed whenever a
    workspace holds more than one product's XML export, since BM-native ids
    (rule/function/attribute ids from the source system) are only unique
    WITHIN one export and do collide across catalogs sharing a workspace.
    Empty catalog_prefix preserves the original workspace-wide match.
    """
    return f"{catalog_prefix.lower()}%{suffix}" if catalog_prefix else f"%{suffix}"
