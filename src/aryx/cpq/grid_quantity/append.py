"""Appending the still-pending grid-quantity questions onto a turn's
pending list (Phase 4 step 3 extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Needs the live ``CpqEngine`` instance (``engine`` param): the SVX
mounting-type queue-jump check calls
``engine._is_svx_mounting_array_quantity_attr``, which stays in
``engine.py``.
"""

from __future__ import annotations

from aryx.cpq.grid_quantity.finalize import _finalize_grid_selections_from_quantities
from aryx.cpq.grid_quantity.links import resolve_array_grid_links
from aryx.cpq.grid_quantity.pending import resolve_pending_grid_quantities
from aryx.cpq.state import ConfigAttr
from aryx.raven_log import raven_log, would_log


def _pending_selectors_only() -> bool:
    from aryx.config import get_settings  # noqa: PLC0415 -- flag-gated

    return bool(get_settings().cpq_grid_quantity_pending_selectors_only_enabled)


def append_pending_grid_quantities(
    engine, pending: list[ConfigAttr], attrs: list[ConfigAttr],
    filled: dict[str, str], filled_multi: dict[str, list[str]],
    filled_source: dict[str, str] | None = None,
    constrained_opts: dict[int, list[str]] | None = None,
    selector_vns: set[str] | None = None,
    workspace_id: int | None = None,
    catalog_prefix: str = "",
    dt_cache: dict[tuple[int, str], tuple] | None = None,
) -> list[ConfigAttr]:
    """Add `resolve_pending_grid_quantities`'s output to `pending`
    (mutated in place, also returned for call-site convenience),
    skipping anything already present.

    SVX mounting-type queue-jump (narrow, catalog-scoped — live-
    confirmed 2026-08-24, not a general rule): a grid-quantity attr is
    only just unlocked THIS pass by the customer's own selection, yet
    a plain append lands it behind mountType_viSoln whenever that
    unrelated sibling merely ranks earlier in the catalog's native
    layout order. A customer who just picked a mount option should be
    asked its quantity before being asked about a completely
    different "Mounting Type" field. Every OTHER catalog/attr keeps
    the plain append-to-end behavior.

    2026-08-25 (explicit product decision, upfront per-option
    quantities): before appending, first calls
    `_finalize_grid_selections_from_quantities` — once every real
    linked option for a not-yet-selected grid selector has its own
    quantity answered, its filled_multi entry is synthesized right
    here, so it naturally drops out of `pending` on this same pass
    instead of lingering. The selector's OWN "choose one" question is
    also excluded from `pending` while its per-option quantities are
    still being asked (resolve_pending_grid_quantities now seeds ALL
    real linked options, not just already-selected ones, for exactly
    this not-yet-selected case) — replaced entirely by the per-option
    flow, never asked redundantly alongside it.

    A selector that already carries a REAL customer selection (a
    filled_multi entry present BEFORE this call — i.e. the customer
    answered its "choose one" question directly rather than going
    through the upfront per-option flow) is left standing in
    `pending` untouched: that's the upstream grid-selector-multi-row
    flow's territory (grid_selector_remaining_options/auto_fill's
    grid_declined_vns), which re-offers the selector across turns
    until the customer declines further rows. The upfront flow only
    ever owns a selector from its unselected state through to its own
    synthesis — it must never swallow a selector upstream's flow is
    actively driving.

    constrained_opts — optional (default `None`) — threaded straight
    through to `resolve_pending_grid_quantities`/`_finalize_grid_
    selections_from_quantities`; see their docstrings for the model/
    constraint-narrowing gap this closes.

    selector_vns -- optional (default None, all grid selectors in
    `attrs`). When given, restricts which selectors' quantity attrs
    this call may surface/append. Callers resolving one specific,
    already-known selector (e.g. label-collision resolution in
    ask_api.py) must pass this -- otherwise, with more than one
    grid-linked multi-select in the catalog, an unrelated selector's
    quantity attr can be appended ahead of/instead of the intended
    one (Raven review, PR #283).
    """
    pre_existing_multi = set(filled_multi.keys())
    pending_before = {a.variable_name for a in pending}
    _finalize_grid_selections_from_quantities(
        attrs, filled, filled_multi, filled_source, constrained_opts)
    links = resolve_array_grid_links(attrs)
    if selector_vns is not None:
        links = {vn: m for vn, m in links.items() if vn in selector_vns}
    # Only strip a selector that the upfront flow itself owns: one
    # with no real selection yet (mid per-option flow) or one just
    # finalized above. A selector already real-selected before this
    # call is left alone for upstream's re-ask flow to handle.
    pending = [
        a for a in pending
        if not (a.variable_name in links and a.variable_name not in pre_existing_multi)
    ]
    seen = {a.variable_name for a in pending}
    if selector_vns is None and _pending_selectors_only():
        # A selector the pass did not leave pending was decided (not applicable, answered, declined): its options are
        # not seeded as quantity questions.
        selector_vns = {vn for vn in links if vn in pending_before or vn in filled_multi or vn in filled}
        skipped = sorted(set(links) - selector_vns)
        if skipped and would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ask.grid_quantity.selectors_skipped selectors the pass left unasked are not seeded",
                      context={"selected_option": "skipped", "available_options": ["seeded", "skipped"],
                               "reason_code": "SELECTOR_NOT_PENDING", "skipped_count": len(skipped),
                               "skipped_selectors": skipped[:20]})
    for qty_attr in resolve_pending_grid_quantities(
        attrs, filled, filled_multi, constrained_opts, selector_vns=selector_vns,
        workspace_id=workspace_id, catalog_prefix=catalog_prefix, dt_cache=dt_cache,
    ):
        if qty_attr.variable_name in seen:
            continue
        if engine._is_svx_mounting_array_quantity_attr(qty_attr) and any(
            a.variable_name == "mountType_viSoln" for a in pending
        ):
            mt_idx = next(
                i for i, a in enumerate(pending) if a.variable_name == "mountType_viSoln"
            )
            pending.insert(mt_idx, qty_attr)
        else:
            pending.append(qty_attr)
        seen.add(qty_attr.variable_name)
    return pending
