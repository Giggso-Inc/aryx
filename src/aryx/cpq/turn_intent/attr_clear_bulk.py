"""Attr-clear / bulk-quantity-change turn detectors (Phase 4 step 2
extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Both need the live ``CpqEngine`` instance (``engine`` param):
``detect_attr_clear`` re-simulates ``engine.apply_recommendation_rules``/
``engine.apply_constraint_rules`` against a trial state, and
``detect_bulk_quantity_change`` reads grid-selector links via
``engine.resolve_array_grid_links``.
"""

from __future__ import annotations

from aryx.cpq.bml.bml import BmlEvaluator
from aryx.cpq.engine import _label_mentioned_strict, _variable_words
from aryx.cpq.state import ConfigAttr, ConstraintRule, RecommendationRule
from aryx.cpq.turn_intent.patterns2 import _BULK_QTY_RE, _CLEAR_VERB_RE


def detect_attr_clear(
    engine,
    question: str,
    attrs: list[ConfigAttr],
    filled: dict[str, str],
    rec_rules: list[RecommendationRule],
    con_rules: list[ConstraintRule],
    bml_eval: BmlEvaluator | None = None,
    workspace_id: int | None = None,
    catalog_prefix: str = "",
) -> ConfigAttr | None:
    """Detect "clear X"/"unset X" nullifying an optional single-select
    attribute's CURRENT value back to blank (D4) — never a required
    attr, and never one a still-active rule would immediately refill.

    Live-checked, not a static flag: simulates removing each
    candidate from `filled` and re-runs
    apply_recommendation_rules/apply_constraint_rules against that
    trial state — if a recommendation would refire, or a constraint
    narrows the attr to exactly one remaining valid option, clearing
    is refused (the very next rule pass would just put the same value
    straight back, silently, making the "clear" a no-op at best).
    """
    if not _CLEAR_VERB_RE.search(question):
        return None
    q_lower = question.lower()
    for attr in attrs:
        vn = attr.variable_name
        if attr.required or attr.select_type == "multi":
            continue
        if not filled.get(vn):
            continue
        if not _label_mentioned_strict(attr.display_label.lower(), q_lower):
            continue
        trial_filled = dict(filled)
        trial_filled.pop(vn, None)
        rec_fires = engine.apply_recommendation_rules(
            attrs, trial_filled, rec_rules, bml_eval=bml_eval)
        if vn in rec_fires:
            continue  # a recommendation would immediately refill it
        constrained = engine.apply_constraint_rules(
            attrs, con_rules, trial_filled, bml_eval=bml_eval,
            workspace_id=workspace_id, catalog_prefix=catalog_prefix)
        allowed = constrained.get(attr.entity_id)
        if allowed is not None:
            valid_opts = [o for o in attr.options if o.item_value in allowed]
            if len(valid_opts) == 1:
                continue  # constraint narrows to one — would refill immediately
        return attr
    return None

def detect_bulk_quantity_change(
    engine,
    question: str,
    attrs: list[ConfigAttr],
    filled_multi: dict[str, list[str]],
) -> "tuple[str, list[str], str] | None":
    """Detect "change both/all the mounting types quantity to 67" — set
    every currently-selected grid-row's quantity to one value at once.

    Live-verified gap: this phrasing was previously misread as a
    single-attribute value change ("change Mounting Type to 67"),
    which either mis-set the grid selector's own value or, on a
    catalog with two identically-labeled "Mounting Type" attrs (one
    single-select, one the real multi-select grid), forced an
    unresolvable disambiguation prompt — 67 was never going to be a
    valid answer for either one, since the real target is each row's
    quantity attr, not the selector's own value.

    Restricting candidates to `resolve_array_grid_links`' selectors
    sidesteps that label collision entirely: a plain single-select
    sibling (e.g. mountType_viSoln) never has grid links and so is
    never a candidate here, regardless of a shared display_label.

    Returns (selector_variable_name, item_values_to_update, new_qty)
    or None. Only matches selectors with at least one already-selected,
    quantity-resolvable row — never guesses at an unfilled selector.
    """
    m = _BULK_QTY_RE.search(question)
    if not m:
        return None
    new_qty = m.group(1)
    grid_links = engine.resolve_array_grid_links(attrs)
    if not grid_links:
        return None
    by_vn = {a.variable_name: a for a in attrs}
    candidates: list[tuple[str, list[str]]] = []
    for selector_vn, item_map in grid_links.items():
        selected = filled_multi.get(selector_vn) or []
        resolvable = [iv for iv in selected if iv.strip().lower() in item_map]
        if resolvable:
            candidates.append((selector_vn, resolvable))
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][0], candidates[0][1], new_qty
    # Multiple grid selectors are in play — narrow by word overlap
    # against each selector's own display_label rather than guess.
    q_words = set(_variable_words(question.replace("_", " ")))
    scored = []
    for selector_vn, resolvable in candidates:
        attr = by_vn.get(selector_vn)
        label_words = set(_variable_words(attr.display_label)) if attr else set()
        if q_words & label_words:
            scored.append((selector_vn, resolvable))
    if len(scored) == 1:
        return scored[0][0], scored[0][1], new_qty
    return None
