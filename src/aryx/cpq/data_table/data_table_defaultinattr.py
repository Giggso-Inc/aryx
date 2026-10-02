"""Default value for (BaseModel, attribute) from Defaultinattr-shaped rows.

Aryxent only planned this table; this is the minimal shape + lookup. A row is
``BaseModel`` + ``attrN``/``valN`` pairs (no CPQModel): for the row's base
model (or ``ALL``), each ``attrN`` has default ``valN``.
"""
from __future__ import annotations

from typing import Any

from aryx.cpq.data_table.data_table_loader import _load_defaultinattr_rows
from aryx.cpq.data_table.data_table_shapes import _attr_val_col_pairs


def resolve_defaultinattr_value(
    base_model: str, attr_var_name: str, workspace_id: int,
    catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
) -> str | None:
    """The default `attr_var_name` value for `base_model`, or None.

    Rows naming the exact base model win over ``ALL`` rows. Within a tier,
    a single distinct value is returned; 2+ distinct values are ambiguous
    and yield None (never guess)."""
    if not base_model or not attr_var_name:
        return None
    exact: set[str] = set()
    generic: set[str] = set()
    for row in _load_defaultinattr_rows(workspace_id, catalog_prefix, cache):
        row_bm = str(row.get("BaseModel") or "").strip()
        bucket = exact if row_bm == base_model else generic if row_bm.upper() == "ALL" else None
        if bucket is None:
            continue
        for attr_col, val_col in _attr_val_col_pairs(set(row.keys())):
            val = row.get(val_col)
            if row.get(attr_col) == attr_var_name and val not in (None, ""):
                bucket.add(str(val))
    for tier in (exact, generic):
        if len(tier) == 1:
            return next(iter(tier))
        if tier:
            return None
    return None
