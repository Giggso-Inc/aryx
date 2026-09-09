"""Data-Table Seriesmodelsmapping option-exclusion helper -- part of the
Data-Table-conflict helper cluster extracted from ``cpq/engine.py``
(Phase 4 step 1, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Stateless,
purely-functional wrapper over already-external ``data_table_resolver``
calls.
"""

from __future__ import annotations

from aryx.cpq.data_table.data_table_resolver import (
    resolve_invalid_product_variant as dt_resolve_invalid_product_variant,
)
from aryx.cpq.state import ConfigAttr


def _apply_series_mapping_exclusions(
    attrs: list[ConfigAttr], constrained_opts: dict[int, list[str]],
    filled: dict[str, str], workspace_id: int | None, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> None:
    """Real Oracle CPQ Seriesmodelsmapping Data Table narrowing for
    productSelectionProduct_all -- mutates `constrained_opts` IN PLACE. Only
    ever REMOVES options a real ingested row explicitly says aren't valid
    here -- never adds a constraint where none of this data applies.
    `None`/no workspace_id (default) is a complete no-op.
    """
    if workspace_id is None:
        return
    target = next(
        (a for a in attrs if a.variable_name == "productSelectionProduct_all"), None,
    )
    if target is None:
        return
    existing = constrained_opts.get(target.entity_id)
    candidates = (
        [o for o in target.options if o.item_value in existing]
        if existing is not None else target.options
    )
    excluded: set[str] = set()
    for opt in candidates:
        override = dt_resolve_invalid_product_variant(
            opt.display_name, opt.item_value, filled, workspace_id, catalog_prefix, cache,
        )
        if override is not None:
            excluded.add(opt.item_value)
    if not excluded:
        return
    if existing is not None:
        constrained_opts[target.entity_id] = [v for v in existing if v not in excluded]
    else:
        constrained_opts[target.entity_id] = [
            o.item_value for o in target.options if o.item_value not in excluded
        ]
