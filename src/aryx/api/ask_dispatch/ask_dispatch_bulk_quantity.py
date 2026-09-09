"""BULK_QUANTITY_CHANGE branch of `_dispatch_intent_result`, split out of
`api/ask_api.py` (Phase 7/11-phase ask_api decomposition, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original
inline `if` block. `_cpq_engine` and `_with_classify_usage` are read
through the ask_api MODULE object (not imported by name) since ask_api
tests patch several of its own module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_attr_recompute.ask_attr_query_and_classify_usage import _with_classify_usage
from aryx.api.ask_handle.ask_handle_bulk_quantity_change import _handle_bulk_quantity_change
from aryx.api.ask_catalog.ask_target_description import _resolve_target_description
from aryx.cpq.engine import is_valid_product_quantity
from aryx.cpq.intent_schema import _is_signed_digit_quantity_text


def _dispatch_bulk_quantity_change(
    result: Any, req: "Any", session: Any, attrs: list,
    hiding_rules: list, rec_rules: list, con_rules: list,
    classify_prompt_tokens: int, classify_completion_tokens: int,
) -> dict[str, Any] | None:
    """docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md Phase 4:
    BULK_QUANTITY_CHANGE is in MUTATING_CATEGORIES so it has already
    passed deterministic agreement upstream (same shape as MULTI_SELECT_
    REMOVAL/ATTR_ACTIVATION/ATTR_CLEAR) — but `quantity_description` is
    free-form text the LLM stated, never a candidate-list selection, so
    it's re-verified here against the exact same predicate `detect_bulk_
    quantity_change` itself uses: the target must resolve to a real
    array-grid selector (never a plain single-select sibling sharing its
    display_label), it must have at least one currently-selected,
    quantity-resolvable row, and the stated quantity must be a real,
    in-range quantity — never guessed at, never applied to an unselected
    or unresolvable row.

    Review finding, 2026-08-13: was a plain `_qty.isdigit()` check. Two
    distinct problems fixed together: (1) `.isdigit()` rejects a leading
    "-", the same bug class `_is_signed_digit_quantity_text` exists to
    fix elsewhere; (2) unlike PRODUCT_QUANTITY_CHANGE's builder,
    `_handle_bulk_quantity_change` does NOT validate `new_qty` at all —
    it writes it straight into `session.filled`/`display_filled` for
    every resolved row. Explicitly checking `is_valid_product_quantity`
    here — not inside `_handle_bulk_quantity_change`, which the
    deterministic `detect_bulk_quantity_change` call site also feeds and
    is out of scope for this fix — keeps this dispatch site's behavior
    unchanged for negative values (still falls through, same as before)
    while additionally closing a real latent gap: "0" is a digit string
    `.isdigit()` accepted but is BELOW MIN_PRODUCT_QUANTITY, so it used
    to be written into a grid row completely unvalidated; it now
    correctly falls through instead.
    """
    from aryx.api import ask_api as _ask_api_module
    if not result.target or not result.quantity_description:
        return None
    attr, _candidates = _resolve_target_description(
        result.target.target_description, attrs)
    if attr is None:
        return None
    _grid_links = _ask_api_module._cpq_engine.resolve_array_grid_links(attrs)
    _item_map = _grid_links.get(attr.variable_name)
    if not _item_map:
        return None
    _selected = session.filled_multi.get(attr.variable_name) or []
    _resolvable = [
        iv for iv in _selected if iv.strip().lower() in _item_map
    ]
    if not _resolvable:
        return None
    _qty = result.quantity_description.strip()
    if not _is_signed_digit_quantity_text(_qty) or not is_valid_product_quantity(int(_qty)):
        return None
    return _with_classify_usage(
        _handle_bulk_quantity_change(
            req, session, attrs, attr.variable_name, _resolvable, _qty,
            hiding_rules, rec_rules, con_rules,
        ),
        classify_prompt_tokens, classify_completion_tokens,
    )
