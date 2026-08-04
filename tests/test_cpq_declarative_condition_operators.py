"""Declarative condition operator handling (docs/CPQ_DECLARATIVE_CONDITION_
OPERATOR_PLAN_2026_08_05.md).

bm_config_rule_input.operator1 was never read anywhere in this codebase —
every declarative condition was evaluated as plain "=" regardless of the
real BM-authored operator. Confirmed via cross-referencing 31 independently
-authored real rule names containing "not"/"non-"/"unless" against their
raw operator1 values: 31/31 use operator1="3" with the value being exactly
the concept being negated (e.g. "...For Non Federal" -> operator="3",
value="FEDERAL"). Read as "<>" this matches every rule's own name; read as
"=" (the old behavior) it means the rule can never fire for anyone, since
the checked attribute is virtually always something other than the exact
excluded value.

Confirmed operator mapping: "4"="=" (majority/default, unchanged),
"3"="<>", "1"="<", "2"="<=", "5"=">". "7"/"8" are a still-unresolved
membership/contains variant and deliberately fall back to "=" (unchanged,
not a new guess) until a follow-up investigation resolves them.
"""
from __future__ import annotations

from aryx.cpq.bml import _operator_hit, evaluate_declarative_conditions
from aryx.cpq.engine import CpqEngine, _condition_value_matches
from aryx.cpq.state import ConfigAttr, HidingRule, MenuOption, RecommendationRule


# ---- _operator_hit: the shared core ---------------------------------------

def test_operator_4_equals_unchanged_behavior():
    assert _operator_hit("FEDERAL", ["FEDERAL"], "4") is True
    assert _operator_hit("COMMERCIAL", ["FEDERAL"], "4") is False


def test_operator_3_not_equal():
    # The confirmed real shape: "...For Non Federal" -> operator=3, value=FEDERAL.
    assert _operator_hit("COMMERCIAL", ["FEDERAL"], "3") is True
    assert _operator_hit("FEDERAL", ["FEDERAL"], "3") is False


def test_operator_3_not_equal_with_tilde_expansion():
    # Real shape: "Hide ATAK attributes if not FED and Canada and Israel"
    # -> operator=3, value="CA~IL" (country not in {CA, IL}).
    assert _operator_hit("US", ["CA~IL"], "3") is True
    assert _operator_hit("CA", ["CA~IL"], "3") is False
    assert _operator_hit("IL", ["CA~IL"], "3") is False


def test_operator_1_less_than():
    assert _operator_hit("30", ["37"], "1") is True
    assert _operator_hit("37", ["37"], "1") is False
    assert _operator_hit("40", ["37"], "1") is False


def test_operator_2_less_than_or_equal():
    assert _operator_hit("0", ["0"], "2") is True
    assert _operator_hit("-1", ["0"], "2") is True
    assert _operator_hit("1", ["0"], "2") is False


def test_operator_5_greater_than():
    assert _operator_hit("12", ["11"], "5") is True
    assert _operator_hit("11", ["11"], "5") is False
    assert _operator_hit("10", ["11"], "5") is False


def test_numeric_operator_non_numeric_input_returns_none_never_guessed():
    assert _operator_hit("not a number", ["37"], "1") is None
    assert _operator_hit("30", ["not a number"], "1") is None


def test_operators_7_and_8_fall_back_to_equals_unchanged():
    # Deliberately unresolved (see module docstring) -- must not silently
    # invert or guess a membership semantic that hasn't been confirmed.
    assert _operator_hit("FEDERAL", ["FEDERAL"], "7") is True
    assert _operator_hit("COMMERCIAL", ["FEDERAL"], "7") is False
    assert _operator_hit("FEDERAL", ["FEDERAL"], "8") is True
    assert _operator_hit("COMMERCIAL", ["FEDERAL"], "8") is False


# ---- evaluate_declarative_conditions: multi-row AND/OR + operators --------

def test_declarative_conditions_replays_real_non_federal_shape():
    # "Restrict Federal Bundle and Front Panel Programming For Non Federal"
    conditions = [(1, "FEDERAL", "3")]
    assert evaluate_declarative_conditions(conditions, {1: "COMMERCIAL"}) == (True, False)
    assert evaluate_declarative_conditions(conditions, {1: "FEDERAL"}) == (False, False)


def test_declarative_conditions_replays_real_mcn_end_user_shape():
    # "Hide MCN END USER attribute for non-Federal and non-Israel customers"
    # customerType<>"FEDERAL" AND country<>"IL"
    conditions = [(1, "FEDERAL", "3"), (2, "IL", "3")]
    # Normal US commercial customer -> both clauses true -> fires (True).
    assert evaluate_declarative_conditions(conditions, {1: "", 2: "US"}) == (True, False)
    # Federal customer -> first clause false -> does not fire.
    assert evaluate_declarative_conditions(conditions, {1: "FEDERAL", 2: "US"}) == (False, False)
    # Israel customer -> second clause false -> does not fire.
    assert evaluate_declarative_conditions(conditions, {1: "", 2: "IL"}) == (False, False)


def test_declarative_conditions_numeric_range_shape():
    # "Set TRUE if DMS Promotional Duration (Months) < than 37"
    conditions = [(1, "37", "1")]
    assert evaluate_declarative_conditions(conditions, {1: "30"}) == (True, False)
    assert evaluate_declarative_conditions(conditions, {1: "40"}) == (False, False)


def test_declarative_conditions_missing_variable_still_unresolved():
    conditions = [(1, "FEDERAL", "3")]
    assert evaluate_declarative_conditions(conditions, {}) == (None, True)


def test_declarative_conditions_and_short_circuit_unchanged_with_operators():
    # A definitively-false AND-ed clause must short-circuit even when a
    # LATER clause's variable is missing -- same contract as before,
    # now proven to still hold with a non-"=" operator in the mix.
    conditions = [(1, "FEDERAL", "3"), (2, "IL", "3")]
    assert evaluate_declarative_conditions(conditions, {1: "FEDERAL"}) == (False, False)


# ---- _condition_value_matches: the scalar single-row path -----------------

def test_scalar_condition_value_matches_defaults_to_equals():
    assert _condition_value_matches("FEDERAL", "FEDERAL") is True
    assert _condition_value_matches("COMMERCIAL", "FEDERAL") is False


def test_scalar_condition_value_matches_respects_not_equal_operator():
    assert _condition_value_matches("COMMERCIAL", "FEDERAL", "3") is True
    assert _condition_value_matches("FEDERAL", "FEDERAL", "3") is False


# ---- End-to-end: apply_hiding_rules / apply_recommendation_rules ----------

def _attr(entity_id: int, vn: str) -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, source_id=entity_id, variable_name=vn,
        display_label=vn, required=False, default_value="",
        options=[MenuOption(item_value="X", display_name="X", order=1)],
    )


def test_hiding_rule_with_not_equal_condition_fires_for_the_common_case():
    """Replays the real bug shape end-to-end: a hiding rule meant to fire
    for the COMMON case (non-federal customers) via operator="3", which
    previously never fired at all because "3" was silently treated as "="."""
    attrs = [_attr(1, "customerType"), _attr(2, "mcnEndUser")]
    rules = [
        HidingRule(
            rule_name="Hide MCN END USER attribute for non-Federal customers",
            condition_attr_id=0, condition_value="", target_attr_id=2,
            conditions=[(1, "FEDERAL", "3")],
        ),
    ]
    eng = CpqEngine()
    visible, _msgs, hidden_vns = eng.apply_hiding_rules(
        attrs, {"customerType": "COMMERCIAL"}, rules, bml_eval=None)
    assert "mcnEndUser" in hidden_vns, (
        "a non-federal customer must have MCN End User hidden -- this is "
        "the common case the rule's own name says it should cover"
    )


def test_hiding_rule_with_not_equal_condition_does_not_fire_for_federal():
    attrs = [_attr(1, "customerType"), _attr(2, "mcnEndUser")]
    rules = [
        HidingRule(
            rule_name="Hide MCN END USER attribute for non-Federal customers",
            condition_attr_id=0, condition_value="", target_attr_id=2,
            conditions=[(1, "FEDERAL", "3")],
        ),
    ]
    eng = CpqEngine()
    visible, _msgs, hidden_vns = eng.apply_hiding_rules(
        attrs, {"customerType": "FEDERAL"}, rules, bml_eval=None)
    assert "mcnEndUser" not in hidden_vns


def test_recommendation_rule_with_not_equal_condition():
    attrs = [_attr(1, "customerType"), _attr(2, "target")]
    rules = [
        RecommendationRule(
            rule_name="Recommend for non-federal", condition_attr_id=0,
            condition_value="", target_attr_id=2, recommended_value="X",
            conditions=[(1, "FEDERAL", "3")],
        ),
    ]
    eng = CpqEngine()
    new_fills = eng.apply_recommendation_rules(
        attrs, {"customerType": "COMMERCIAL"}, rules, bml_eval=None)
    assert new_fills.get("target") == ("X", "X")
