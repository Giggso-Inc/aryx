"""BML Tier-2 prefetch request builder plus the context-sentence builder
(Phase 4 step 7 extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

``CpqEngine._attr_index`` is reached through the engine MODULE object
rather than imported by name so that a per-class replacement of
``_attr_index`` is still honored, exactly as the original in-class
``CpqEngine._attr_index(...)`` call was.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq import engine as _engine_module
from aryx.cpq.state import (
    ConfigAttr, ConstraintRule, HidingRule, RecommendationRule,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aryx.cpq.engine import CpqEngine


def bml_prefetch_requests(
    filled: dict[str, str],
    attrs: list[ConfigAttr] | None = None,
    hiding: list[HidingRule] | None = None,
    rec: list[RecommendationRule] | None = None,
    con: list[ConstraintRule] | None = None,
) -> list[tuple[str, str, dict[str, str], int | None]]:
    """Build BmlEvaluator.prefetch_tier2 requests for every script-backed
    rule in the given rule sets, against the CURRENT `filled` state.

    Amendment 18 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): mirrors
    exactly what apply_hiding_rules/apply_recommendation_rules/
    apply_constraint_rules will each independently ask
    hide_for_script/condition_holds/allowed_values_for_script for --
    same rule fields, same `filled` argument, no cache_id (those call
    sites never pass one either, so both sides key on hash(script)).
    Coverage gaps here only cost speed, never correctness: an
    uncovered rule's script just isn't pre-warmed and falls through to
    its normal sequential call, exactly as if this method didn't run.

    `rec` also mirrors apply_recommendation_rules' own "already filled"
    skip (needs `attrs` to resolve target_attr_id -> variable_name) so
    a prefetch doesn't burn concurrent Tier-2 calls on rules that loop
    will never actually consult this pass. `hiding`/`con` have no such
    skip in their own apply_* methods (visibility and allowed-value
    narrowing both apply regardless of current fill state), so none is
    replicated here either.
    """
    reqs: list[tuple[str, str, dict[str, str], int | None]] = []
    for rule in (hiding or []):
        if rule.script is not None:
            reqs.append(("hide", rule.script, filled, None))
    if rec:
        by_rule_id = _engine_module.CpqEngine._attr_index(attrs or [])
        for rule in rec:
            target = by_rule_id.get(rule.target_attr_id)
            if not target or filled.get(target.variable_name):
                continue
            if rule.script is not None:
                reqs.append(("values", rule.script, filled, None))
            elif rule.condition_script is not None:
                reqs.append(("cond", rule.condition_script, filled, None))
    for rule in (con or []):
        if rule.script is not None:
            reqs.append(("values", rule.script, filled, None))
        elif rule.condition_script is not None:
            reqs.append(("cond", rule.condition_script, filled, None))
    return reqs


def build_context_sentence(
    engine: CpqEngine,
    pending_attr: ConfigAttr,
    attrs: list[ConfigAttr],
    filled: dict[str, str],
    display_filled: dict[str, str],
    hiding_rules: list[HidingRule],
    rec_rules: list[RecommendationRule],
) -> str:
    """Explain WHY this attribute is being asked, based on fired rules.

    Returns a sentence like "Since X was set to Y, we now need Z." or ""
    when no rule relationship is found (attribute is independently
    required).
    """
    by_rule_id = engine._attr_index(attrs)
    pending_ids = {pending_attr.entity_id}
    if pending_attr.source_id is not None:
        pending_ids.add(pending_attr.source_id)

    # A show-type hiding rule revealed this attr
    for rule in hiding_rules:
        if rule.target_attr_id not in pending_ids or rule.hide:
            continue
        cond_attr = by_rule_id.get(rule.condition_attr_id)
        if cond_attr and cond_attr.variable_name in filled:
            disp_val = display_filled.get(
                cond_attr.variable_name, filled[cond_attr.variable_name]
            )
            return (
                f"Since we locked in **{disp_val}**, "
                f"please choose the **{pending_attr.display_label}**."
            )

    # A recommendation rule targeted this attr (but had multiple valid options)
    for rule in rec_rules:
        if rule.target_attr_id not in pending_ids:
            continue
        cond_attr = by_rule_id.get(rule.condition_attr_id)
        if cond_attr and cond_attr.variable_name in filled:
            disp_val = display_filled.get(
                cond_attr.variable_name, filled[cond_attr.variable_name]
            )
            return (
                f"Since we locked in **{disp_val}**, "
                f"please choose the **{pending_attr.display_label}**."
            )

    return ""
