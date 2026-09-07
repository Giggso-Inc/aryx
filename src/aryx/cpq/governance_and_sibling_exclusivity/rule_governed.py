"""The strict rule-only governance set and the "Product"-label noise
detector built on top of it (Phase 4 step 7 extraction from
``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

``CpqEngine._attr_index`` and ``CpqEngine.rule_governed_ids`` are
reached through the engine MODULE object rather than imported by name,
preserving the original in-class ``CpqEngine.<name>(...)`` dispatch
exactly (class-level replacements stay honored; the instance-level
``monkeypatch.setattr(api._cpq_engine, "rule_governed_ids", ...)`` used
by some tests was never visible to this call site and still isn't).
"""

from __future__ import annotations

from aryx.cpq import engine as _engine_module
from aryx.cpq.state import (
    ConfigAttr, ConstraintRule, HidingRule, RecommendationRule,
)


def rule_governed_ids(
    attrs: list[ConfigAttr],
    hiding_rules: list[HidingRule],
    rec_rules: list[RecommendationRule],
    con_rules: list[ConstraintRule],
) -> set[int]:
    """Entity ids of attrs targeted by at least one loaded rule.

    D2 (CPQ_CASCADE_CONVERSATION_PLAN.md 2): an attribute only counts as
    a "dependent variable" eligible for default-or-first auto-fill if a
    hiding, recommendation, or constraint rule actually targets it --
    everything else keeps the existing ask-the-user safeguard (Issue 6).
    This is the strict subset `auto_fill` tags `filled_source="rule"`;
    see `governed_target_ids` for the wider Phase N eligibility set.
    """
    by_rule_id = _engine_module.CpqEngine._attr_index(attrs)
    governed: set[int] = set()
    for rule in hiding_rules:
        target = by_rule_id.get(rule.target_attr_id)
        if target:
            governed.add(target.entity_id)
    for rule in rec_rules:
        target = by_rule_id.get(rule.target_attr_id)
        if target:
            governed.add(target.entity_id)
    for rule in con_rules:
        target = by_rule_id.get(rule.target_attr_id)
        if target:
            governed.add(target.entity_id)
    return governed


def product_label_noise_vns(
    attrs: list[ConfigAttr],
    hiding_rules: list[HidingRule],
    rec_rules: list[RecommendationRule],
    con_rules: list[ConstraintRule],
) -> set[str]:
    """Variable names of "Product"-labeled attrs that are genuinely
    irrelevant noise once `session.model_leaf_resolved` is True -- the
    CommandCentral-style case Amendment 10 was built for, where a
    generic "Product" attr carries no rule of its own and the real
    model identity travels entirely through the resolved bm_catalog
    leaf instead.

    Deliberately NOT every attr labeled "Product" -- live-confirmed bug
    (2026-07-28): APX Next's order text ("Order APX Next Radios...")
    also matches one of the workspace's catalog leaf candidates in the
    ambiguous-multi-leaf resolution path, setting model_leaf_resolved
    True for APX Next as well -- but unlike CommandCentral, APX Next's
    own "Product" attr (productSelectionProduct_all) IS a genuine,
    rule-governed decision (a real constraint script narrows its
    options by Hardware Version). The blanket "drop every Product-
    labeled attr" rule silently dropped it from `pending` AND the
    payload entirely, with no value ever collected. Scoping to
    `rule_governed_ids` (a purely structural signal -- which rules
    already target which attrs, independent of current filled state)
    distinguishes "truly noise, no rule cares about this" from "a real
    rule narrows this, it must still be asked."
    """
    governed = _engine_module.CpqEngine.rule_governed_ids(
        attrs, hiding_rules, rec_rules, con_rules
    )
    return {
        a.variable_name for a in attrs
        if a.display_label.strip().lower() == "product"
        and a.entity_id not in governed
    }
