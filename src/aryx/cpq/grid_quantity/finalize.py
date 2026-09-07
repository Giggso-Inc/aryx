"""Synthesizing a grid selector's own selection from its per-option
quantity answers (Phase 4 step 3 extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Stateless and purely
functional -- no ``CpqEngine`` instance needed.
"""

from __future__ import annotations

from aryx.cpq.engine import _valid
from aryx.cpq.grid_quantity.links import resolve_array_grid_links
from aryx.cpq.state import ConfigAttr


def _finalize_grid_selections_from_quantities(
    attrs: list[ConfigAttr], filled: dict[str, str],
    filled_multi: dict[str, list[str]],
    filled_source: dict[str, str] | None = None,
    constrained_opts: dict[int, list[str]] | None = None,
) -> None:
    """Once EVERY real grid-linked option for a not-yet-selected
    selector has its own quantity answered (2026-08-25's upfront
    per-option flow — see `resolve_pending_grid_quantities`),
    synthesize the selector's own `filled_multi` entry from the
    options that got a real, positive quantity — a "0" or blank
    quantity simply means that option isn't included. Mutates
    `filled_multi` in place. A selector already answered (via a
    real selection or an earlier synthesis) is left untouched;
    never re-derives over a customer's own explicit choice.

    filled_source — optional (default `None`, no-op for a caller
    that doesn't track provenance). When given, also stamps the
    synthesized selector as `"user"` — live-confirmed gap (2026-08-26):
    without this, the selector's `filled_multi` entry has no
    provenance at all, so `build_payload`'s `scope_required_and_edited`
    preview (`_is_mandatory_input_attr`, which requires a confirmed
    source) silently drops the ENTIRE array-set wrapper — every
    answered mount quantity — from the JSON preview, even though each
    one was individually, genuinely confirmed by the customer. This is
    a real, derived-but-confirmed decision, exactly as legitimate as
    one the customer typed directly onto the selector itself.

    constrained_opts — optional (default `None`) — see
    `resolve_pending_grid_quantities`'s own docstring for the exact
    gap this closes: without it, a not-yet-selected selector's
    `filled_multi` synthesis (and the "all linked options answered"
    completeness check) would consider options outside the currently
    valid model/constraint set.
    """
    links = resolve_array_grid_links(attrs)
    if not links:
        return
    by_vn = {a.variable_name: a for a in attrs}
    for selector_vn, item_map in links.items():
        if selector_vn in filled_multi or selector_vn in filled:
            continue
        selector_attr = by_vn.get(selector_vn)
        if selector_attr is None:
            continue
        allowed = (
            constrained_opts.get(selector_attr.entity_id) if constrained_opts else None
        )
        linked_options = [
            o for o in selector_attr.options
            if o.item_value.strip().lower() in item_map
            and (allowed is None or o.item_value in allowed)
        ]
        if not linked_options:
            continue
        qty_vns = {item_map[o.item_value.strip().lower()] for o in linked_options}
        # Digit-only, not just present -- a non-numeric value stored in
        # `filled` (e.g. by an unrelated bug upstream) must not be read
        # as an answered quantity here (Raven review, PR #283).
        if not all(
            qty_vn in filled and filled[qty_vn].strip().isdigit() for qty_vn in qty_vns
        ):
            continue  # still waiting on at least one option's quantity
        selected_values = [
            o.item_value for o in linked_options
            if _valid(filled.get(item_map[o.item_value.strip().lower()], ""))
            and filled[item_map[o.item_value.strip().lower()]].strip() not in ("0", "")
        ]
        filled_multi[selector_vn] = selected_values
        if filled_source is not None:
            filled_source[selector_vn] = "user"
