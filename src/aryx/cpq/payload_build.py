"""Orchestrator for `build_payload` (Phase 4, one of the 8 previously-
deferred oversized `CpqEngine` methods, docs/RAVEN_STYLE_COMPLIANCE_PLAN_
2026-09-03.md). Ties together `payload_setup.build_context`, the scalar/
multi-select serialization stages, array-set row grouping, and final key
ordering. Logic unchanged from the original inline body.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.payload_array_sets import group_array_set_rows
from aryx.cpq.payload_multi import serialize_multi_attrs
from aryx.cpq.payload_order import order_payload_keys
from aryx.cpq.payload_scalar import serialize_scalar_attrs
from aryx.cpq.payload_setup import build_context


def build_payload(
    engine: Any,
    filled: dict[str, str],
    filled_source: dict[str, str] | None = None,
    filled_multi: dict[str, list[str]] | None = None,
    attrs: list[Any] | None = None,
    hidden_vns: set[str] | None = None,
    rules: list[Any] | None = None,
    display_order: dict[str, int] | None = None,
    product_quantity: int | None = None,
    scope_required_and_edited: bool = False,
    workspace_id: int | None = None,
    catalog_prefix: str = "",
) -> dict[str, Any]:
    """See `CpqEngine.build_payload`'s docstring (src/aryx/cpq/engine.py)
    for the full contract — kept there since it documents caller-facing
    behavior, not this module's internal split.
    """
    ctx = build_context(
        engine, filled, filled_source, filled_multi, attrs, hidden_vns, rules,
        scope_required_and_edited, workspace_id, catalog_prefix,
    )
    serialize_scalar_attrs(engine, ctx, filled, scope_required_and_edited)
    serialize_multi_attrs(engine, ctx, filled_multi, scope_required_and_edited)
    group_array_set_rows(ctx, attrs, filled)
    ordered_keys = order_payload_keys(engine, ctx, rules, display_order)

    result: dict[str, Any] = {"configData": {k: ctx.out[k] for k in ordered_keys}}
    if product_quantity is not None:
        result["quantity"] = product_quantity
    return result
