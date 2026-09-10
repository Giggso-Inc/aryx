"""Cascade-dependent-attr lookup and Step 6 review-prompt building (Phase 4
step 2 extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Both need the live ``CpqEngine`` instance (``engine`` param):
``find_cascade_dependents`` uses ``engine._attr_index`` to resolve rule
target_attr_ids to entity_ids, and ``build_review_prompt`` uses
``engine._is_html_value`` to skip HTML-rendered display values.
"""

from __future__ import annotations

from aryx.cpq.engine import _DECISION_REQUIRED_KEYS
from aryx.cpq.state import ConfigAttr, ConstraintRule, HidingRule, RecommendationRule


def find_cascade_dependents(
    engine,
    changed_attr: "ConfigAttr",
    all_attrs: list[ConfigAttr],
    hiding_rules: list[HidingRule],
    rec_rules: list[RecommendationRule],
    con_rules: list[ConstraintRule],
) -> list[int]:
    """Return entity_ids of attrs that may be invalidated when changed_attr is re-valued.

    Covers:
      - Attrs targeted by hiding/recommendation/constraint rules conditioned on changed_attr.
      - Free-text cascade siblings (attrs sharing a decision key fragment with changed_attr).
    """
    dependents: set[int] = set()
    changed_ids = {changed_attr.entity_id}
    if changed_attr.source_id is not None:
        changed_ids.add(changed_attr.source_id)
    by_rule_id = engine._attr_index(all_attrs)

    def _target_eid(target_attr_id: int) -> int:
        target = by_rule_id.get(target_attr_id)
        return target.entity_id if target else target_attr_id

    for rule in hiding_rules:
        if rule.condition_attr_id in changed_ids:
            dependents.add(_target_eid(rule.target_attr_id))
    for rule in rec_rules:
        if rule.condition_attr_id in changed_ids:
            dependents.add(_target_eid(rule.target_attr_id))
    for rule in con_rules:
        if rule.condition_attr_id in changed_ids:
            dependents.add(_target_eid(rule.target_attr_id))

    # Cascade-fill siblings (free-text attrs that mirror this attr's value)
    changed_vn_flat = changed_attr.variable_name.lower().replace("_", "")
    matched_dk = next(
        (dk for dk in _DECISION_REQUIRED_KEYS if dk in changed_vn_flat), None
    )
    if matched_dk:
        for attr in all_attrs:
            if attr.entity_id == changed_attr.entity_id or attr.options:
                continue
            if matched_dk in attr.variable_name.lower().replace("_", ""):
                dependents.add(attr.entity_id)

    return list(dependents)

def build_review_prompt(
    engine,
    product_name: str,
    attrs: list[ConfigAttr],
    display_filled: dict[str, str],
) -> str:
    """Build the Step 6 review message for user approval.

    Shows decision-required attrs (the choices the user made) prominently,
    and summarises auto-configured attrs as a count so the review is scannable.
    """
    by_vn: dict[str, ConfigAttr] = {a.variable_name: a for a in attrs}
    decision_lines: list[str] = []
    auto_count = 0

    for vn, disp_val in display_filled.items():
        if engine._is_html_value(disp_val):
            continue
        attr = by_vn.get(vn)
        label = attr.display_label if attr else vn
        vn_flat = vn.lower().replace("_", "")
        is_decision = any(dk in vn_flat for dk in _DECISION_REQUIRED_KEYS)
        if is_decision:
            decision_lines.append(f"- **{label}**: {disp_val}")
        else:
            auto_count += 1

    parts = [f"✅ **{product_name}** is configured. Review your choices:"]
    if decision_lines:
        parts.extend(decision_lines)
    if auto_count:
        parts.append(f"\n*{auto_count} additional attributes auto-configured from graph defaults.*")
    parts.append(
        "\nSay **confirm** to generate the BOM, or describe what you'd like to change."
    )
    return "\n".join(parts)
