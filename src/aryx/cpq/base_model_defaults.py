"""The Defaultinattr defaults of one base model, as an {attribute: value} map built once.

`resolve_defaultinattr_value` answers one attribute and walks every row of the table (thousands) for it; asking it
for each of the ~3,000 attributes of a full-catalog pass is far too slow. This builds the same answer for all
attributes in one walk and keeps it in the caller's per-turn cache. Same rules: rows naming the exact base model win
over ``ALL`` rows, and an attribute with two or more distinct defaults in the winning tier is ambiguous and has none
(never guess).
"""
from __future__ import annotations

from typing import Any

from aryx.cpq.data_table.data_table_loader import _load_defaultinattr_rows
from aryx.cpq.data_table.data_table_shapes import _attr_val_col_pairs


def base_model_defaults(
    base_model: str, workspace_id: int, catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
) -> dict[str, str]:
    """{attribute: default value} for `base_model` (compared case-insensitively, like ``ALL``); empty without a
    base model or table."""
    wanted = (base_model or "").strip().upper()
    if not wanted:
        return {}
    key = (workspace_id, catalog_prefix, "base_model_defaults", wanted)
    if cache is not None and key in cache:
        return cache[key]
    exact: dict[str, set[str]] = {}
    generic: dict[str, set[str]] = {}
    for row in _load_defaultinattr_rows(workspace_id, catalog_prefix, cache):
        row_bm = str(row.get("BaseModel") or "").strip()
        tier = exact if row_bm.upper() == wanted else generic if row_bm.upper() == "ALL" else None
        if tier is None:
            continue
        for attr_col, val_col in _attr_val_col_pairs(set(row.keys())):
            attr, val = row.get(attr_col), row.get(val_col)
            if attr and val not in (None, ""):
                tier.setdefault(str(attr), set()).add(str(val))
    out: dict[str, str] = {}
    for attr in {*exact, *generic}:
        values = exact.get(attr) or generic.get(attr) or set()
        if len(values) == 1:
            out[attr] = next(iter(values))
    if cache is not None:
        cache[key] = out
    return out


def base_model_own_defaults(
    base_model: str, workspace_id: int, catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
) -> dict[str, set[str]]:
    """{attribute: its default values} from the Defaultinattr rows that name `base_model` itself (``ALL`` rows excluded).

    `base_model_defaults` answers "what is the default"; this answers "which attributes does this base model define
    defaults for", which tells the base models of one model apart (the one carrying the model's default configuration
    defines more of them than its siblings)."""
    wanted = (base_model or "").strip().upper()
    if not wanted:
        return {}
    key = (workspace_id, catalog_prefix, "base_model_own_defaults", wanted)
    if cache is not None and key in cache:
        return cache[key]
    out: dict[str, set[str]] = {}
    for row in _load_defaultinattr_rows(workspace_id, catalog_prefix, cache):
        if str(row.get("BaseModel") or "").strip().upper() != wanted:
            continue
        for attr_col, val_col in _attr_val_col_pairs(set(row.keys())):
            attr, val = row.get(attr_col), row.get(val_col)
            if attr and val not in (None, ""):
                out.setdefault(str(attr), set()).add(str(val))
    if cache is not None:
        cache[key] = out
    return out
