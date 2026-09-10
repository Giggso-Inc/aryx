"""Grid-selector option bookkeeping: what's still pickable, and which
already-picked options have no resolvable quantity attr at all (Phase 4
step 3 extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Stateless and purely
functional -- no ``CpqEngine`` instance needed.
"""

from __future__ import annotations

from aryx.cpq.engine import _valid
from aryx.cpq.grid_quantity.links import resolve_array_grid_links
from aryx.cpq.state import ConfigAttr, MenuOption


def grid_selector_remaining_options(
    attr: ConfigAttr,
    filled_multi: dict[str, list[str]],
    constrained_opts: dict[int, list[str]] | None,
) -> list[MenuOption]:
    """Currently-valid options of a grid-selector attr the customer
    hasn't picked yet.

    Structural and catalog-agnostic: `filled_multi` gives what's
    already chosen, `constrained_opts` (apply_constraint_rules'
    output, same active-rule narrowing already used to build the
    question prompt) gives what's still legal for the current
    configuration. Neither param names any attribute or catalog.
    """
    picked = set(filled_multi.get(attr.variable_name) or [])
    allowed = (
        set(constrained_opts[attr.entity_id])
        if constrained_opts and attr.entity_id in constrained_opts
        else None
    )
    return [
        o for o in attr.options
        if _valid(o.item_value) and o.item_value not in picked
        and (allowed is None or o.item_value in allowed)
    ]


def unresolved_grid_quantity_options(
    attrs: list[ConfigAttr], filled_multi: dict[str, list[str]],
) -> list[tuple[str, str]]:
    """Selected grid-selector options with NO resolvable quantity attr
    at all (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 9).

    `resolve_array_grid_links`'s own token-matching deliberately skips
    an option when its token is too short or ambiguous (matches 2+
    quantity-attr candidates) — confirmed live real example: SVX's
    bare "Magnetic Mount" option (distinct from "Jacket Magnetic
    Mount"/"Shirt Magnetic Mount") has no dedicated quantity attr in
    the catalog's own data at all (`qty_attr_id` is unpopulated,
    `-1`, catalog-wide — not authoritative), so its token
    "magneticmount" ambiguously matches BOTH siblings' quantity attrs
    and is correctly never guessed. Left unchecked, that selection's
    quantity is silently, permanently unaskable, yet the conversation
    still declares "Configuration complete" with a real per-row gap.

    Returns (selector_display_label, item_value) pairs for every
    selected option that participates in the grid-quantity mechanism
    (the selector has at least one OTHER option that DOES resolve —
    proving this is a real per-row-quantity construct, not a plain
    multi-select) but has no resolvable link of its own — so the
    caller can surface and block on this instead of completing.
    """
    links = resolve_array_grid_links(attrs)
    if not links:
        return []
    by_vn = {a.variable_name: a for a in attrs}
    unresolved: list[tuple[str, str]] = []
    for selector_vn, item_map in links.items():
        selector = by_vn.get(selector_vn)
        if selector is None:
            continue
        for item_value in filled_multi.get(selector_vn) or []:
            if item_value.strip().lower() not in item_map:
                unresolved.append((selector.display_label, item_value))
    return unresolved
