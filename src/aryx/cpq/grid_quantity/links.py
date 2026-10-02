"""Array-grid control discovery and the visible-selector -> hidden
per-option quantity-attr link heuristic (Phase 4 step 3 extraction from
``cpq/engine.py``, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Stateless and purely functional -- no ``CpqEngine`` instance needed.
"""

from __future__ import annotations

import re

from aryx.config import get_settings
from aryx.cpq.state import ConfigAttr


def array_grid_controls_in_play(attrs: list[ConfigAttr]) -> list[str]:
    """Variable names of is_array_control_attr=1 attrs present in this
    catalog (e.g. an array-control driving a mounting-type quantity
    grid) — flagged, never auto-populated.

    Investigated and deliberately NOT auto-filled
    (docs/CPQ_SVX_LAYOUT_FLOW_AND_QUANTITY_GRID_PLAN.md §5 Change B
    follow-up): the real link between a customer's grid-row selection
    and its per-row quantity attr lives only in BigMachines' own
    native-UI array-control JavaScript widget — confirmed by a
    full-file scan of the raw XML finding ZERO bm_config_rule_input
    rows referencing the visible row-selector attr at all. Any
    code-side mapping would have to guess from variable-name patterns
    (e.g. "Shirt Magnetic Mount" -> mountingTypeShirtMagneticMount
    Quantity_viSoln), which is catalog-specific and unverifiable —
    exactly the guessing this engine's design principle forbids
    elsewhere (D2 "never guess"). This surfaces the gap instead of
    silently mis-populating or silently dropping it.
    """
    return sorted({a.variable_name for a in attrs if a.is_array_control})


def resolve_array_grid_links(attrs: list[ConfigAttr]) -> dict[str, dict[str, str]]:
    """Best-effort variable-name heuristic linking a visible menu-based
    selector attr's options to hidden ``*Quantity*``-named attrs (kept
    in `attrs` for exactly this purpose — see load_product_config's
    drop-filter exception).

    Explicitly NOT rule-derived — array_grid_controls_in_play()'s own
    docstring and docs/CPQ_SVX_LAYOUT_FLOW_AND_QUANTITY_GRID_PLAN.md §5
    confirm no such link exists in any ingested rule data. This is a
    deliberate, explicitly requested exception to this engine's
    "never guess" default, scoped as tightly as possible: a match only
    counts when EXACTLY ONE quantity candidate's normalized
    variable_name contains the option's normalized text (>=6 alnum
    chars, to avoid trivial/short-token false positives like "1" or
    "US"). Ambiguous or too-short tokens are skipped silently — never
    guessed. Returns {selector_vn: {item_value_lower: quantity_vn}}.

    When ``cpq_rule_governed_hidden_attr_guard_enabled`` is on,
    ``is_value_rule_target`` attrs are excluded from the candidates: a
    hidden attr a REAL rule already governs gets its value from rule/BML
    data, and must never be linked (and surfaced as an unanswerable
    pending question) via this name-substring guess. Flag off: unchanged.
    """
    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    guard = bool(get_settings().cpq_rule_governed_hidden_attr_guard_enabled)
    qty_candidates = [
        a for a in attrs
        if a.hidden and "quantity" in a.variable_name.lower()
        and not (guard and a.is_value_rule_target)
    ]
    if not qty_candidates:
        return {}
    qty_norm = [(a.variable_name, norm(a.variable_name)) for a in qty_candidates]

    links: dict[str, dict[str, str]] = {}
    for attr in attrs:
        if attr.hidden or not attr.options:
            continue
        item_map: dict[str, str] = {}
        # Live-confirmed gap (2026-08-26, real BOM API rejection —
        # "Index 6/10/11 ... is not Valid"): two DIFFERENT real
        # options can share a common substring -- "MOLLE Mount"'s
        # normalized token is itself a substring of the longer,
        # more specific "Locking Molle Mount"'s own quantity attr
        # name (`...LockingMolleMountQuantity...`), and likewise
        # "Belt Mount" inside "TEK-LOK Belt Mount"'s. Naively
        # matching per-option let BOTH options claim the SAME
        # quantity attr, synthesizing a phantom extra array-set row
        # for an option the customer never actually selected.
        # Processing longest-token-first and removing a quantity
        # candidate once claimed ensures the longer, more specific
        # option's own genuine match wins that candidate before a
        # shorter, coincidentally-overlapping option ever gets a
        # chance at it -- the shorter option then correctly finds no
        # (remaining) match instead of stealing someone else's.
        opts_by_token_len = sorted(
            (
                (opt, norm(opt.display_name or opt.item_value))
                for opt in attr.options
            ),
            key=lambda ot: -len(ot[1]),
        )
        claimed_vns: set[str] = set()
        for opt, token in opts_by_token_len:
            if len(token) < 6:
                continue
            matches = [
                vn for vn, qn in qty_norm
                if token in qn and vn not in claimed_vns
            ]
            if len(matches) == 1:
                item_map[opt.item_value.strip().lower()] = matches[0]
                claimed_vns.add(matches[0])
        if item_map:
            links[attr.variable_name] = item_map
    return links
