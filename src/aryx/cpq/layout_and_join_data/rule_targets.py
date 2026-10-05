"""Rule-key / target-resolution helpers over the join data
``_load_rule_join_data`` returns, plus the structural operator-collision
exclusion the declarative loaders gate on (Phase 4 step 5 extraction from
``cpq/engine.py``, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

All three were ``@staticmethod``s that touch nothing on the instance, so
none takes an ``engine`` parameter.
"""

from __future__ import annotations

from aryx.config import get_settings


def _resolve_targets(
    rule_key: int,
    actions_by_rule: dict[int, list[tuple[int, int, str, int, int, str]]],
    marked_by_rule: dict[int, list[int]],
    chain_by_rule: dict[int, int],
    max_hops: int = 3,
) -> list[tuple[int, int]]:
    """Resolve a rule's target attribute(s), following the real linkage.

    Priority: (1) BmConfigRuleAction (still correct for exports that use
    it), (2) BmConfigMarkedAttr — may yield multiple targets, one per
    marked attribute, (3) BmConfigRuleAssoc chaining to a child rule,
    re-resolved through (1)-(2) at the terminal rule (bounded depth).
    Returns [(target_attr_id, action_type)] — action_type defaults to 2
    (hide) for marked-attr-sourced targets since no hide/show signal has
    ever been observed to vary in real data (see §6a).
    """
    acts = actions_by_rule.get(rule_key, [])
    if acts:
        return [(aid, at) for aid, at, _v, _f, _st, _c in acts]
    marked = marked_by_rule.get(rule_key)
    if marked:
        return [(aid, 2) for aid in marked]
    seen: set[int] = {rule_key}
    current = chain_by_rule.get(rule_key)
    hops = 0
    while current is not None and current not in seen and hops < max_hops:
        acts = actions_by_rule.get(current, [])
        if acts:
            return [(aid, at) for aid, at, _v, _f, _st, _c in acts]
        marked = marked_by_rule.get(current)
        if marked:
            return [(aid, 2) for aid in marked]
        seen.add(current)
        current = chain_by_rule.get(current)
        hops += 1
    return []


def _rule_key(entity_id: int, source_id: int | None,
              inputs: dict, actions: dict) -> int:
    """Pick the id that BmConfigRuleInput/Action rows actually reference."""
    if source_id is not None and (source_id in inputs or source_id in actions):
        return source_id
    return entity_id


def _condition_has_operator_collision(conditions: list[tuple[int, str, str]]) -> bool:
    """True if any single attribute in `conditions` is checked with 2+
    DISTINCT operators — docs/CPQ_SAME_ATTRIBUTE_OPERATOR_COLLISION_
    PLAN_2026_08_05.md.

    evaluate_declarative_conditions groups same-attribute rows under a
    single shared operator (the first row's); for rows that genuinely
    share one operator (an OR-list of acceptable/excluded values) this
    is correct, but for rows with DIFFERENT operators on the same
    attribute it silently drops every row after the first — confirmed
    live via "Restrict Number Of Seats between 1 and 12" (`< 1` and
    `> 12` on the same attribute; only `< 1` would ever be checked).

    Confirmed catalog-wide (80 real rules across 4 catalogs) that no
    single combining rule fixes this correctly for every shape yet —
    two patterns are confirmed for 76% of cases, but forcing them in
    now would silently mis-evaluate the remaining ~24% (see the plan
    doc). Used as a purely structural, never-guessed exclusion: a rule
    hitting this collision is skipped entirely (same as if it were
    never confirmed) rather than loaded with a guessed combining rule.
    """
    if getattr(conditions, "expression", "") and get_settings().cpq_condition_expression_enabled:
        return False    # plan F3: the rule's own expression decides, no operator collision to avoid
    by_attr: dict[int, set[str]] = {}
    for attr_id, _value, operator in conditions:
        by_attr.setdefault(attr_id, set()).add(operator)
    return any(len(ops) > 1 for ops in by_attr.values())
