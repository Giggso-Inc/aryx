"""Narrow CPQ models by the ingested series-mapping table (plan F8).

A series page lists several child models, and the series-mapping table says
which children are offered for which country or region (one or more rows per
child, each with attrN/opN/valN conditions). A child that is not offered for the
quote's country must not contribute required attributes. The link from a child
to its CPQ model is the whitelist itself: a constraint row that names the
product-selector attribute in a condition column carries the child as the value
and the CPQ model in the same row. Nothing here names a product, model,
country or attribute: the conditions' attributes come from the table rows.

A row whose condition cannot be decided yet (attribute not filled, unknown
operator) never removes a child, and the result never becomes empty.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from aryx.cpq.bml.bml_declarative import _operator_hit
from aryx.cpq.catalog_profile import PRODUCT_LITERAL
from aryx.cpq.data_table.data_table_loader import _load_all_tables

_OPERATORS = {"=": "4", "4": "4", "<>": "3", "!=": "3", "3": "3"}


def _row_state(row: dict[str, Any], filled: dict[str, str]) -> bool | None:
    """True / False when every condition of a series row is decided, None when
    one is not (the row then keeps its child)."""
    state: bool | None = True
    n = 1
    while f"attr{n}" in row:
        attr = str(row.get(f"attr{n}") or "").strip()
        if attr:
            op = _OPERATORS.get(str(row.get(f"op{n}") or "").strip())
            current = (filled.get(attr) or "").strip()
            if op is None or not current:
                state = None
            else:
                values = [v.strip() for v in str(row.get(f"val{n}") or "").split(",") if v.strip()]
                if not _operator_hit(current, values, op):
                    return False
        n += 1
    return state


def _child_models(constraint_rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    """child (product value) -> CPQModels, from the whitelist rows that name
    the product selector in a condition column."""
    out: dict[str, set[str]] = defaultdict(set)
    for row in constraint_rows:
        model = row.get("CPQModel")
        if not model:
            continue
        n = 1
        while f"attr{n}" in row:
            if row.get(f"attr{n}") == PRODUCT_LITERAL and row.get(f"val{n}"):
                out[str(row[f"val{n}"])].add(str(model))
            n += 1
    return out


def blocked_children(
    filled: dict[str, str], workspace_id: int, catalog_prefix: str = "", cache: dict | None = None,
) -> set[str]:
    """Series children whose every row is decided False for the current country/region."""
    constraint_rows, _seq, _hier, series_rows, _region = _load_all_tables(workspace_id, catalog_prefix, cache)
    states: dict[str, list[bool | None]] = defaultdict(list)
    for row in series_rows:
        child = str(row.get("childCPQModel") or "")
        if child:
            states[child].append(_row_state(row, filled))
    return {child for child, rows in states.items() if rows and all(s is False for s in rows)}


def narrow_models_by_series(
    models: list[str], filled: dict[str, str], workspace_id: int,
    catalog_prefix: str = "", cache: dict | None = None,
) -> list[str]:
    """`models` without those whose only series children are not offered for
    the quote's country/region; `models` unchanged when nothing can be decided."""
    blocked = blocked_children(filled, workspace_id, catalog_prefix, cache)
    if not blocked:
        return models
    constraint_rows, *_ = _load_all_tables(workspace_id, catalog_prefix, cache)
    children_of: dict[str, set[str]] = defaultdict(set)
    for child, cpq_models in _child_models(constraint_rows).items():
        for cpq_model in cpq_models:
            children_of[cpq_model].add(child)
    kept = [m for m in models if not children_of.get(m) or not children_of[m] <= blocked]
    return kept or models
