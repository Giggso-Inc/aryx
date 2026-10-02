"""Which grid-quantity attrs are still pending an answer (Phase 4 step 3
extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Stateless and purely
functional -- no ``CpqEngine`` instance needed.
"""

from __future__ import annotations

from aryx.cpq.grid_quantity.links import resolve_array_grid_links
from aryx.cpq.grid_quantity.narrow import whitelist_narrowed_selector_options
from aryx.cpq.state import ConfigAttr


def resolve_pending_grid_quantities(
    attrs: list[ConfigAttr], filled: dict[str, str],
    filled_multi: dict[str, list[str]],
    constrained_opts: dict[int, list[str]] | None = None,
    selector_vns: set[str] | None = None,
    workspace_id: int | None = None,
    catalog_prefix: str = "",
    dt_cache: dict[tuple[int, str], tuple] | None = None,
) -> list[ConfigAttr]:
    """Extra pending ConfigAttrs for grid-quantity attrs whose selector
    has a selected row without a quantity yet (resolve_array_grid_links).

    Each returned attr is a REAL ConfigAttr from `attrs` — asked via the
    same free-text pending mechanism as any other attribute (these
    quantity attrs have no menu options, so apply_answer's free-text
    numeric path handles the reply). No new UI/ask concept needed.

    2026-08-25 (explicit product decision): when the selector itself
    has NO selection recorded at all yet (never answered, no
    filled_multi entry, no filled entry), every one of its real,
    grid-linked options is treated as pending its own quantity —
    instead of first asking the customer to pick which options they
    want, every real option gets its own quantity question directly
    (blank/"0" answers simply exclude that option later — see
    `_finalize_grid_selections_from_quantities`). Generic: keyed only
    on `resolve_array_grid_links`'s own resolution, no catalog/
    attribute name hardcoded. Once the selector DOES have a real
    selection (customer answered normally, or a prior turn already
    started this per-option flow and filled_multi was synthesized),
    this reverts to the original "only already-selected rows" set —
    never re-asks an option the customer explicitly excluded.

    constrained_opts — optional (default `None`, preserving prior
    behavior of seeding every raw catalog option) — the same
    `apply_constraint_rules` output (keyed by entity_id) the normal
    "choose one" pending-question path already narrows its own option
    list with. Live-confirmed gap (2026-08-26, SVX base model "SVX
    Video Remote Speaker Mic"): without this, the upfront flow asked
    for a quantity on EVERY raw-catalog option resolve_array_grid_
    links could token-match — including TEK-LOK Belt Mount, valid
    only for the TAA variant, not the base model actually selected.
    When given and the selector's entity_id has a narrowed set, only
    those item_values are treated as real/selectable here.

    selector_vns -- optional (default None, all grid selectors in
    `attrs`). When given, restricts resolution to only these
    selectors' own linked quantity attrs. Needed by callers resolving
    a single, specific selector (e.g. label-collision resolution in
    ask_api.py): without this, a catalog with more than one grid-
    linked multi-select can have an unrelated selector's quantity
    attr returned here instead (Raven review, PR #283).
    """
    if dt_cache is None and workspace_id is not None:
        dt_cache = {}  # share one Whitelist index across selectors in this call
    links = resolve_array_grid_links(attrs)
    if selector_vns is not None:
        links = {vn: m for vn, m in links.items() if vn in selector_vns}
    if not links:
        return []
    by_vn = {a.variable_name: a for a in attrs}
    extra: list[ConfigAttr] = []
    seen: set[str] = set()
    for selector_vn, item_map in links.items():
        selected = filled_multi.get(selector_vn) or (
            [filled[selector_vn]] if selector_vn in filled and filled[selector_vn] else []
        )
        if not selected and selector_vn not in filled_multi and selector_vn not in filled:
            selector_attr = by_vn.get(selector_vn)
            if selector_attr is not None:
                allowed = (
                    constrained_opts.get(selector_attr.entity_id)
                    if constrained_opts else None
                )
                if allowed is None:
                    # D17: Whitelist narrowing (flag-gated; None when off).
                    allowed = whitelist_narrowed_selector_options(
                        selector_vn, filled, workspace_id, catalog_prefix, dt_cache,
                    )
                # Case-insensitive ("700/800 MHz" vs "700/800 MHZ"), like
                # constraint_rules_intersect.normalize.
                allowed_lower = (
                    None if allowed is None else {a.strip().lower() for a in allowed}
                )
                selected = [
                    o.item_value for o in selector_attr.options
                    if o.item_value.strip().lower() in item_map
                    and (allowed_lower is None or o.item_value.strip().lower() in allowed_lower)
                ]
        for item_value in selected:
            qty_vn = item_map.get(item_value.strip().lower())
            if not qty_vn or qty_vn in filled or qty_vn in seen:
                continue
            qty_attr = by_vn.get(qty_vn)
            if qty_attr is None:
                continue
            extra.append(qty_attr)
            seen.add(qty_vn)
    return extra
