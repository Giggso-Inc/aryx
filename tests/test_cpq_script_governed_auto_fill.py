"""Regression coverage: auto_fill's "single/boolean, 2+ options, first-by-
menu-order" fallback must never blind-pick an option for an attr governed
ONLY by a script-based recommendation rule without actually evaluating
that script.

Live-verified bug (2026-07-24): "wouldYouLikeToIncludeABatterySubscription_
viSoln" is targeted by exactly one recommendation rule, script-only
(condition_attr_id=0 — no declarative condition at all):
    if (includeASpareBatteryWithEachBodyCamera_viSoln == true) return "YES";
    return "";
Because this attr has a real rec_rule pointing at it, `governed_ids`
marks it "rule-governed" -- but `_satisfied_recommendation` (auto_fill's
own pre-check, meant to let a satisfied recommendation win before the
blind first-by-order pick) only ever inspected the plain
condition_attr_id/condition_value pair, never rule.script. So it always
returned None for this attr, and execution fell through to "first by
menu order", picking the first-listed option "YES" -- regardless of the
real spare-battery value -- every single time, even when the script's
own condition was false.
"""
from __future__ import annotations

from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption, RecommendationRule


_SCRIPT = (
    'if( (spareBattery_viSoln == true)){\n'
    '\treturn "YES";\n'
    '}\n'
    'return "";'
)


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _attrs() -> list[ConfigAttr]:
    subscription = ConfigAttr(
        entity_id=1, variable_name="subscription_viSoln", display_label="Include a Battery Subscription?",
        required=False, default_value="", select_type="single",
        options=_menu("YES", "No"), source_id=101,
    )
    spare_battery = ConfigAttr(
        entity_id=2, variable_name="spareBattery_viSoln", display_label="Include a Spare Battery",
        required=False, default_value="false", select_type="single",
        options=[], source_id=102,
    )
    return [subscription, spare_battery]


def _rec_rule() -> RecommendationRule:
    return RecommendationRule(
        rule_name="Set defaults", condition_attr_id=0, condition_value="",
        target_attr_id=101, recommended_value="", script=_SCRIPT,
    )


def test_script_governed_attr_not_blind_picked_when_condition_is_false():
    eng = CpqEngine()
    attrs = _attrs()
    bml_eval = BmlEvaluator(scripts={}, use_llm=False, workspace_id=id(attrs))
    filled, display_filled, pending = eng.auto_fill(
        attrs, hints={}, already_filled={"spareBattery_viSoln": "false"},
        governed_ids={1}, rule_governed_ids={1}, rec_rules=[_rec_rule()],
        bml_eval=bml_eval,
    )
    assert filled.get("subscription_viSoln") != "YES", (
        "subscription must not blind-pick YES when the script's own condition is false"
    )


def test_script_governed_attr_resolves_correctly_when_condition_is_true():
    eng = CpqEngine()
    attrs = _attrs()
    bml_eval = BmlEvaluator(scripts={}, use_llm=False, workspace_id=id(attrs))
    filled, display_filled, pending = eng.auto_fill(
        attrs, hints={}, already_filled={"spareBattery_viSoln": "true"},
        governed_ids={1}, rule_governed_ids={1}, rec_rules=[_rec_rule()],
        bml_eval=bml_eval,
    )
    assert filled.get("subscription_viSoln") == "YES"


def test_script_governed_attr_without_bml_eval_never_guesses():
    eng = CpqEngine()
    attrs = _attrs()
    filled, display_filled, pending = eng.auto_fill(
        attrs, hints={}, already_filled={"spareBattery_viSoln": "false"},
        governed_ids={1}, rule_governed_ids={1}, rec_rules=[_rec_rule()],
        bml_eval=None,
    )
    assert filled.get("subscription_viSoln") != "YES"
