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
"3"="<>", "1"="<", "2"="<=", "5"=">" (Phase 1). "7"="intersects"/
"8"="disjoint from" (Phase 2) — a multi-select ("~"-joined current-
selection set) membership check, confirmed via 104/110 real op7/op8 rows
targeting an attribute classify_select_type independently calls "multi"
(the remaining 6 are all _BM_USER_GROUPS, a BM system membership
pseudo-attribute) plus 4 independently-authored rule-name cross-checks
with zero contradictions once accounting for the standard convention that
a *validation* rule's own condition encodes the failure state, not its
name's positive framing (e.g. "...only when Enhancement Level is
selected" uses op8 on both candidate values as the BLOCK condition —
fires when NEITHER is selected).
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


def test_operator_7_scalar_behaves_like_equals():
    # A scalar actual value (no "~") is just a one-element set -- op7's
    # intersection check degrades to plain membership, same as op4.
    assert _operator_hit("FEDERAL", ["FEDERAL"], "7") is True
    assert _operator_hit("COMMERCIAL", ["FEDERAL"], "7") is False


def test_operator_8_scalar_behaves_like_not_equal():
    assert _operator_hit("FEDERAL", ["FEDERAL"], "8") is False
    assert _operator_hit("COMMERCIAL", ["FEDERAL"], "8") is True


def test_operator_7_multi_select_intersects():
    # Real shape: "Do not allow Smartlocate to be deselected when
    # Smartvideo or SmartEvidence selected" -- op7 on SMARTVIDEO and op7 on
    # SMARTEVIDENCE, same attribute (an OR-group after grouping).
    expected = ["SMARTVIDEO", "SMARTEVIDENCE"]
    assert _operator_hit("SMARTLOCATE~SMARTEVIDENCE", expected, "7") is True
    assert _operator_hit("SMARTLOCATE~SMARTMAPPING", expected, "7") is False
    assert _operator_hit("", expected, "7") is False


def test_operator_8_multi_select_disjoint():
    # Real shape: "Allow Multi-Code Plug Programming only when Enhancement
    # Level is selected" -- op8 on ENHANCEMENT LEVEL 1 and op8 on
    # ENHANCEMENT LEVEL 2 is the rule's own BLOCK condition, firing when
    # NEITHER is selected.
    expected = ["ENHANCEMENT LEVEL 1", "ENHANCEMENT LEVEL 2"]
    assert _operator_hit("MULTI-CODE PLUG PROGRAMMING", expected, "8") is True
    assert _operator_hit("MULTI-CODE PLUG PROGRAMMING~ENHANCEMENT LEVEL 1", expected, "8") is False
    assert _operator_hit("", expected, "8") is True


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


# ---- _filled_by_rule_id: multi-select plumbing (Phase 2) -------------------
#
# select_type=="multi" attrs' current selections live in filled_multi, a
# structure completely separate from the scalar filled dict -- before this
# fix, apply_hiding_rules/apply_recommendation_rules/apply_constraint_rules
# only ever read `filled`, so ANY declarative condition on a multi-select
# attribute (which is exactly where every real op7/op8 row lives) always
# saw that attribute as "missing" and could never resolve, regardless of
# the operator mapping being correct.

def test_filled_by_rule_id_reads_multi_select_current_value():
    attrs = [_attr(1, "additionalApplicationServices_astro")]
    out = CpqEngine._filled_by_rule_id(
        attrs, {}, {"additionalApplicationServices_astro": ["SMARTVIDEO", "SMARTLOCATE"]})
    assert out[1] == "SMARTVIDEO~SMARTLOCATE"


def test_filled_by_rule_id_missing_when_absent_from_both():
    attrs = [_attr(1, "additionalApplicationServices_astro")]
    assert CpqEngine._filled_by_rule_id(attrs, {}, {}) == {}


def test_filled_by_rule_id_explicit_empty_multi_is_known_not_missing():
    # An explicitly-deselected multi-select (filled_multi[vn] == []) is a
    # real "nothing selected" state, not "unfilled" -- must still resolve
    # (as an empty set) rather than falling through to "missing".
    attrs = [_attr(1, "additionalApplicationServices_astro")]
    out = CpqEngine._filled_by_rule_id(
        attrs, {}, {"additionalApplicationServices_astro": []})
    assert out[1] == ""


def test_hiding_rule_with_op8_condition_fires_when_multi_select_empty():
    """Replays "Hide Smartvideo help text if Smartvideo not selected"
    end-to-end: op8 on SMARTVIDEO, target is a different attr. Must fire
    when the multi-select currently holds nothing (or nothing matching)."""
    attrs = [
        _attr(1, "additionalApplicationServices_astro"),
        _attr(2, "smartvideoHelpText_astro"),
    ]
    rules = [
        HidingRule(
            rule_name="Hide Smartvideo help text if Smartvideo not selected",
            condition_attr_id=0, condition_value="", target_attr_id=2,
            conditions=[(1, "SMARTVIDEO", "8")],
        ),
    ]
    eng = CpqEngine()
    _visible, _msgs, hidden_vns = eng.apply_hiding_rules(
        attrs, {}, rules, bml_eval=None,
        filled_multi={"additionalApplicationServices_astro": ["SMARTLOCATE"]},
    )
    assert "smartvideoHelpText_astro" in hidden_vns


def test_hiding_rule_with_op8_condition_does_not_fire_when_selected():
    attrs = [
        _attr(1, "additionalApplicationServices_astro"),
        _attr(2, "smartvideoHelpText_astro"),
    ]
    rules = [
        HidingRule(
            rule_name="Hide Smartvideo help text if Smartvideo not selected",
            condition_attr_id=0, condition_value="", target_attr_id=2,
            conditions=[(1, "SMARTVIDEO", "8")],
        ),
    ]
    eng = CpqEngine()
    _visible, _msgs, hidden_vns = eng.apply_hiding_rules(
        attrs, {}, rules, bml_eval=None,
        filled_multi={"additionalApplicationServices_astro": ["SMARTVIDEO", "SMARTLOCATE"]},
    )
    assert "smartvideoHelpText_astro" not in hidden_vns


def test_hiding_rule_with_op8_condition_never_fires_without_filled_multi():
    """Without filled_multi threaded through at all (the pre-fix call
    shape), the condition attribute is always "missing" -- the rule can
    never resolve, regardless of what's actually selected. Guards the
    plumbing gap itself, not just the operator mapping."""
    attrs = [
        _attr(1, "additionalApplicationServices_astro"),
        _attr(2, "smartvideoHelpText_astro"),
    ]
    rules = [
        HidingRule(
            rule_name="Hide Smartvideo help text if Smartvideo not selected",
            condition_attr_id=0, condition_value="", target_attr_id=2,
            conditions=[(1, "SMARTVIDEO", "8")],
        ),
    ]
    eng = CpqEngine()
    _visible, _msgs, hidden_vns = eng.apply_hiding_rules(attrs, {}, rules, bml_eval=None)
    assert "smartvideoHelpText_astro" not in hidden_vns
