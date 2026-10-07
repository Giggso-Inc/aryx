"""Declarative bm_config_rule_input condition evaluation (operator codes
1/2/3/4/5/6/7/8), independent of BML script parsing entirely.

Split out of `cpq/bml.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See `bml_text.py`'s docstring for the zero-patch-risk basis.
"""
from __future__ import annotations

from aryx.config import get_settings

_NUMERIC_OPERATORS = frozenset({"1", "2", "5", "6"})  # <, <=, >, >=
_GREATER_THAN_OR_EQUAL_OPERATOR = "6"
# "6" = ">=" -- confirmed 2026-10-07 against ws 1267/Astro25Configdata.
# Rule NAMES alone are ambiguous/misleading here (most literally say ">1",
# a few say "non zero", i.e. >=1 for a non-negative quantity) -- what
# actually resolved it was the validation MESSAGE/constraint ACTION text:
# e.g. "Constrain qty >1 When select is false..." fires with message
# "Please change the quantity to 0 or blank," which only makes business
# sense if the rule fires for qty=1 too (not just 2+) -- a strict ">1"
# reading would silently let qty=1 pass despite the rule clearly meaning
# "quantity must be 0 when unselected." Same for "Restrict Blank
# Selection for Power Supply if SNT Unit ISGREATER than 1": a blank
# Power Supply selection should be disallowed as soon as there's ANY SNT
# unit (qty>=1), not only once there are 2+. ">=" also completes the
# numeric-operator pairing symmetrically: "1"/"2" are the </<=  pair,
# "5"/"6" are the >/>= pair.
_NOT_EQUAL_OPERATOR = "3"
# "7"/"8" — multi-select ("~"-joined current-selection set) membership,
# confirmed via docs/CPQ_DECLARATIVE_CONDITION_OPERATOR_PLAN_2026_08_05.md
# Phase 2: 104/110 real op7/op8 rows target an attribute classify_select_type
# already independently calls "multi" (checkbox); the remaining 6 are all
# _BM_USER_GROUPS, a BM system membership pseudo-attribute — same set-
# intersection semantic, just against the user's group membership set
# instead of a menu attribute's current selections. "7" = the current
# selection set intersects the rule's expected value(s) ("Do not allow
# Smartlocate to be deselected when Smartvideo or SmartEvidence selected"
# uses op7 as an OR across SMARTVIDEO/SMARTEVIDENCE). "8" = the current
# selection set does NOT intersect the expected value(s) ("...only when
# Enhancement Level is selected" uses op8 on both ENHANCEMENT LEVEL 1 and
# LEVEL 2 as the rule's own failure condition -- fires, i.e. blocks, when
# NEITHER is selected; "Hide Smartvideo help text if Smartvideo not
# selected" uses op8 directly on SMARTVIDEO).
_MULTI_SELECT_CONTAINS_OPERATOR = "7"
_MULTI_SELECT_NOT_CONTAINS_OPERATOR = "8"
_MULTI_SELECT_OPERATORS = frozenset(
    {_MULTI_SELECT_CONTAINS_OPERATOR, _MULTI_SELECT_NOT_CONTAINS_OPERATOR}
)


def _operator_hit(actual: str, expected_values: list[str], operator: str) -> bool | None:
    """Does `actual` satisfy `expected_values` under the given BM-native
    operator code? Returns None when a numeric operator can't parse either
    side — never guessed, same D2 discipline as every other unresolvable
    case in this module.

    expected_values may itself contain "~"-delimited OR-lists per value
    (same convention as ConstraintRule.allowed_values) — expanded into a
    flat set for "=", "<>", "7" and "8" (membership / non-membership
    against the whole set). Numeric operators (<, <=, >) compare against
    the single expected value directly — real catalog data never carries a
    "~"-list for a numeric bound (confirmed: docs/CPQ_DECLARATIVE_
    CONDITION_OPERATOR_PLAN_2026_08_05.md's audit found no such case).

    Mapping confirmed via docs/CPQ_DECLARATIVE_CONDITION_OPERATOR_PLAN_
    2026_08_05.md: "4"="=" (default/majority, 31/31 rule-name cross-check
    for "3"), "3"="<>", "1"="<", "2"="<=", "5"=">", "7"="intersects"/
    "8"="disjoint from" (Phase 2, 104/110 real rows target a
    select_type=="multi" attr, cross-checked against 4 independently
    -authored rule names — see the constants above for detail). "6"=">="
    (see _GREATER_THAN_OR_EQUAL_OPERATOR above for the confirmation).

    For "7"/"8", `actual` is itself allowed to be a "~"-joined SET (a
    multi-select attr's current selections), not just a scalar — checked
    via set intersection with `expected_values` rather than the scalar
    membership check the other operators use. A plain scalar with no "~"
    still works correctly here: it just becomes a one-element set.
    """
    actual_norm = actual.strip().lower()
    if operator in _NUMERIC_OPERATORS:
        try:
            actual_num = float(actual)
            expected_num = float(expected_values[0]) if expected_values else None
        except (TypeError, ValueError):
            return None
        if expected_num is None:
            return None
        if operator == "1":
            return actual_num < expected_num
        if operator == "2":
            return actual_num <= expected_num
        if operator == _GREATER_THAN_OR_EQUAL_OPERATOR:  # "6"
            return actual_num >= expected_num
        return actual_num > expected_num  # "5"

    expanded = {
        part.strip().lower()
        for v in expected_values
        for part in v.split("~")
        if part.strip()
    }

    if operator in _MULTI_SELECT_OPERATORS:
        actual_set = {part.strip().lower() for part in actual.split("~") if part.strip()}
        intersects = bool(actual_set & expanded)
        return intersects if operator == _MULTI_SELECT_CONTAINS_OPERATOR else not intersects

    hit = actual_norm in expanded
    if operator == _NOT_EQUAL_OPERATOR:
        return not hit
    return hit  # "4"

def evaluate_declarative_conditions(
    conditions: list[tuple[int, str, str]], variables_by_id: dict[int, str],
) -> tuple[bool | None, bool]:
    """Evaluate a rule's FULL set of bm_config_rule_input rows (not just the
    last one — see HidingRule.conditions / ConstraintRule.conditions /
    RecommendationRule.conditions docstrings for why this replaces the old
    single condition_attr_id/condition_value pair for multi-input rules).

    Grouping rule: the SAME attribute_id repeated across rows means OR (any
    of that attribute's listed values matches, or none of them does for
    "<>" — see _operator_hit); DIFFERENT attribute_ids are ANDed together.
    Confirmed live this matches real data: a rule like "Allow Multi-Code
    Plug Programming only when Enhancement Level is selected" repeats one
    attribute 3x with different ENHANCEMENT LEVEL values (an OR-list)
    alongside 2 other distinct attributes (ANDed in) — a real boolean
    expression, not a simple range.

    operator1 IS now consulted, via _operator_hit — see that function's
    docstring and docs/CPQ_DECLARATIVE_CONDITION_OPERATOR_PLAN_2026_08_05.md
    for the confirmed mapping and why the prior "always =" behavior was
    wrong for 25.5% of real condition rows in one catalog. Every row for
    the same attr_id is assumed to share one operator (mixing "=" and "<>"
    within one OR-group was never observed in the confirmed audit); the
    first row's operator is used for the whole group.

    Returns (result, blocked_by_missing_var):
      - (True, False)  — every attribute-group matched.
      - (False, False) — at least one attribute-group is known and did NOT
        match — short-circuits, same AND semantics as a script AND-chain
        already hitting False (see bml._first_matching_branch).
      - (None, True)   — one or more groups are still unresolved (attribute
        not filled yet) AND none of the known groups already disproved the
        condition — genuinely "not enough information yet," not a grammar
        problem, so callers should treat this the same as
        _first_matching_branch's own (None, True) case (no Tier-2 call,
        no premature fire).
      - (None, False)  — no conditions at all (empty list); callers should
        treat this the same as "no condition" (unresolved/unsupported).
    """
    if not conditions:
        return None, False
    if getattr(conditions, "expression", "") and get_settings().cpq_condition_expression_enabled:
        # plan F3: the rule's own condition_expression over its numbered rows
        from aryx.cpq.bml.bml_condition_expression import evaluate_condition_expression
        try:
            return evaluate_condition_expression(conditions, variables_by_id)
        except ValueError:
            pass    # an expression this evaluator does not support: attribute grouping below
    by_attr: dict[int, list[str]] = {}
    op_by_attr: dict[int, str] = {}
    order: list[int] = []
    for attr_id, value, operator in conditions:
        if attr_id not in by_attr:
            order.append(attr_id)
            op_by_attr[attr_id] = operator
        by_attr.setdefault(attr_id, []).append(value)

    saw_missing = False
    for attr_id in order:
        actual = variables_by_id.get(attr_id)
        if actual is None:
            saw_missing = True
            continue
        # Each row's own value can itself be a "~"-delimited OR-list (same
        # encoding as ConstraintRule.allowed_values, e.g. a single input row
        # storing "PREMIER~ADVANCED SOFTWARE ONLY~ESSENTIAL SOFTWARE ONLY")
        # rather than always one literal value per row — a bare equality
        # check against the whole string can never match any one real value
        # in that case (confirmed live: this is exactly why "Hide Include
        # Accidental Damage for certain Service Type" never fired — see
        # docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md §3). Splitting each
        # row's value here is a strict superset of the old behavior — a
        # row with no "~" splits into a 1-element list, identical to before.
        # _operator_hit handles the "~"-expansion itself.
        hit = _operator_hit(actual, by_attr[attr_id], op_by_attr[attr_id])
        if hit is None:
            saw_missing = True
            continue
        if not hit:
            return False, False
    if saw_missing:
        return None, True
    return True, False
