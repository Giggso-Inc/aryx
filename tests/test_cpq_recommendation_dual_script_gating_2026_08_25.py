"""Regression coverage: a RecommendationRule can carry a script-backed
ACTION and a script-backed CONDITION at the same time -- the action alone
says nothing about WHEN the rule should fire.

Live-confirmed incident (2026-08-25, SVX "Force Set Quantity of Body Worn
Cameras with sum of Mounting"): this rule's action script sums
mountingTypeArrayqty_viSoln across every selected mounting row and force-
sets v300BodyWornCamera_viSoln to that sum; its own gating condition
(fires only once at least one mount quantity is entered, i.e. sum > 0) is
ALSO script-backed via a separate BmFunction. _load_value_rules built the
RecommendationRule with condition_attr_id hardcoded to 0 and no
condition_script attached at all, and apply_recommendation_rules checked
`rule.script is not None` FIRST -- so the condition script was never
consulted, the rule effectively fired unconditionally (or never, if the
loader's own guard skipped it), and v300BodyWornCamera_viSoln stayed
unfilled. MSI's own downstream validation then rejected the submission
as incomplete, since it needs that value to reconcile against the real
mount-quantity sum.

Fix: the loader now attaches condition_script to a script-backed-action
RecommendationRule when the rule's own fn_id is ALSO script-backed, and
apply_recommendation_rules/resync_stale_recommendations both check that
condition_script first (D2 "never guess": unknown/False never fires)
before ever evaluating the action script -- generic to any rule with
this same dual-script shape, no attribute or rule name hardcoded.
"""
from __future__ import annotations

from aryx.cpq.bml.bml import BmlEvaluator, clear_shared_bml_cache
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption, RecommendationRule


def _target_attr() -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="v300BodyWornCamera_viSoln",
        display_label="Quantity of Body Worn Cameras", required=False,
        default_value="", select_type="single",
        options=[MenuOption(item_value="42", display_name="42")],
    )


_CONDITION_SCRIPT = (
    'if (checkSumFlag == "YES") { return true; } else { return false; }'
)
_ACTION_SCRIPT = 'return "42";'


def _dual_script_rule() -> RecommendationRule:
    return RecommendationRule(
        rule_name="Force Set Quantity of Body Worn Cameras with sum of Mounting",
        condition_attr_id=0, condition_value="", target_attr_id=1,
        script=_ACTION_SCRIPT, condition_script=_CONDITION_SCRIPT,
    )


def setup_function(_fn):
    clear_shared_bml_cache()


def test_dual_script_rule_does_not_fire_when_condition_script_is_false():
    attr = _target_attr()
    eng = CpqEngine()
    bml_eval = BmlEvaluator({})
    filled = {"checkSumFlag": "NO"}

    result = eng.apply_recommendation_rules(
        [attr], filled, [_dual_script_rule()], bml_eval=bml_eval,
    )

    assert "v300BodyWornCamera_viSoln" not in result


def test_dual_script_rule_fires_when_condition_script_is_true():
    attr = _target_attr()
    eng = CpqEngine()
    bml_eval = BmlEvaluator({})
    filled = {"checkSumFlag": "YES"}

    result = eng.apply_recommendation_rules(
        [attr], filled, [_dual_script_rule()], bml_eval=bml_eval,
    )

    assert result.get("v300BodyWornCamera_viSoln") == ("42", "42")


def test_action_only_script_rule_is_unaffected_by_the_new_gating():
    """A rule with a script-backed action but NO condition_script (the
    overwhelming majority, e.g. this same catalog's mounting-array-size
    rules) must behave exactly as before -- the action script alone
    still controls firing."""
    attr = _target_attr()
    eng = CpqEngine()
    bml_eval = BmlEvaluator({})
    rule = RecommendationRule(
        rule_name="Action-only script rule", condition_attr_id=0,
        condition_value="", target_attr_id=1, script=_ACTION_SCRIPT,
    )

    result = eng.apply_recommendation_rules([attr], {}, [rule], bml_eval=bml_eval)

    assert result.get("v300BodyWornCamera_viSoln") == ("42", "42")


def test_resync_stale_recommendations_also_gates_on_condition_script():
    """Same dual-script shape, but for the already-filled resync path --
    a stale value must not be re-asserted while the condition is false,
    and must be corrected once it becomes true."""
    attr = _target_attr()
    eng = CpqEngine()
    bml_eval = BmlEvaluator({})
    filled = {"checkSumFlag": "NO", "v300BodyWornCamera_viSoln": "0"}

    result = eng.resync_stale_recommendations(
        [attr], filled, {}, [_dual_script_rule()], bml_eval=bml_eval,
    )
    assert "v300BodyWornCamera_viSoln" not in result

    filled["checkSumFlag"] = "YES"
    result2 = eng.resync_stale_recommendations(
        [attr], filled, {}, [_dual_script_rule()], bml_eval=bml_eval,
    )
    assert result2.get("v300BodyWornCamera_viSoln") == ("42", "42")
