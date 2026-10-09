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
              inputs: dict, actions: dict, marked: dict | None = None) -> int:
    """Pick the id that BmConfigRuleInput/Action/MarkedAttr rows actually
    reference.

    Live-confirmed (ws 1267, rule id 5030760 "Hide do you required Radio
    FED FCC"): a rule with no BmConfigRuleInput condition row and no
    BmConfigRuleAction row -- its only target linkage is a BmConfigMarkedAttr
    row keyed under `source_id`, not `entity_id`. With `marked` omitted (the
    original check), neither id matched inputs/actions, so this fell back to
    `entity_id`, and `_resolve_targets(entity_id, ...)` then missed the real
    marked_attr row -- "no resolvable target" even though one exists.

    Review-confirmed (2026-10-09) this rule is itself UNCONDITIONAL (0
    inputs) and scoped (`ref_id`) to the aPXNext BmCatalog node -- it is not
    "hide for non-Federal customers", and resolving its target here is only
    half the story: whether it actually loads at all still depends on
    `cpq_empty_condition_rule_true_enabled` (off in ws 1267's dev default,
    confirmed live -- this fix alone changes nothing there yet), and
    whether/where it then applies depends on `cpq_rule_scope_filter_enabled`
    and the target product's resolved `scope_node_ids` (empty for a
    table-resolved model like APX 1500 Enhanced, which makes that filter a
    no-op). 103 other ws 1267 type-11 rules share this same no-input/no-
    action/marked-attr-only shape and are equally affected by this fix --
    this change was not evaluated against each of them individually.

    `marked` is consulted ONLY when NEITHER id has a condition/action row --
    review-confirmed (2026-10-09) that checking it as an equal-priority OR
    term is unsafe: a rule whose real conditions/actions are keyed under
    `entity_id` but which also happens to carry an unrelated marked-attr row
    under `source_id` would flip to `source_id`, silently losing its real
    conditions and (with `cpq_empty_condition_rule_true_enabled` on) turning
    a conditional rule into an always-true one. No rule in ws 1267's type-11
    set currently has that exact shape, but the fallback is ordered
    defensively rather than relying on that holding forever. `marked`
    defaults to None so every caller that doesn't resolve marked-attr
    targets (e.g. value_rules_load, which only reads inputs/actions) keeps
    its exact prior behavior.
    """
    if source_id is not None and (source_id in inputs or source_id in actions):
        return source_id
    if (
        marked is not None and source_id is not None
        and entity_id not in inputs and entity_id not in actions
        and entity_id not in marked and source_id in marked
    ):
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
