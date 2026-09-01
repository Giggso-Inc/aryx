"""Regression tests: recommendation-governed attrs must not stay
permanently locked to a stale, engine-derived value once a driving
attribute's real value later disagrees with it (docs/
config_consistency_issues_2026-07-30.md issue 6 — the FedRAMP Yes/No
discrepancy).

CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md §4.1 deliberately never auto-fixes
this class of drift for a CUSTOMER-chosen value ("the engine can't be
certain what the correct value should have been"). These tests instead
cover the narrower, safe case this session added: an engine-derived value
(filled_source not user/hint/cascade) IS safe to resync, since re-running
the same deterministic rule with fresher inputs isn't a guess.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption, RecommendationRule


def _attr(entity_id, variable_name, display_label, options=None):
    opts = [MenuOption(item_value=iv, display_name=dn) for iv, dn in (options or [])]
    return ConfigAttr(
        entity_id=entity_id, variable_name=variable_name,
        display_label=display_label, required=False, default_value="",
        options=opts,
    )


def _rec_rule(condition_attr_id, condition_value, target_attr_id, recommended_value):
    return RecommendationRule(
        rule_name="test rule",
        condition_attr_id=condition_attr_id, condition_value=condition_value,
        target_attr_id=target_attr_id, recommended_value=recommended_value,
    )


def test_resync_corrects_engine_sourced_value_when_condition_now_disagrees():
    """The exact FedRAMP shape: isProvisioningRequiredInCloudEnv_astro=YES
    means isFedRampRequired_astro should be NO, but the target is still
    stuck at YES from an earlier auto-fill pass."""
    driver = _attr(1, "isProvisioningRequiredInCloudEnv_astro", "Is provisioning required?",
                    [("YES", "Yes"), ("NO", "No")])
    target = _attr(2, "isFedRampRequired_astro", "Is FedRAMP High Baseline required?",
                    [("YES", "Yes"), ("NO", "No")])
    rule = _rec_rule(1, "YES", 2, "NO")
    filled = {"isProvisioningRequiredInCloudEnv_astro": "YES", "isFedRampRequired_astro": "YES"}
    filled_source = {"isFedRampRequired_astro": "auto"}

    eng = CpqEngine()
    corrections = eng.resync_stale_recommendations(
        [driver, target], filled, filled_source, [rule], bml_eval=None,
    )
    assert corrections == {"isFedRampRequired_astro": ("NO", "No")}


def test_resync_never_touches_a_customer_sourced_value():
    """The exact §4.1 boundary — a value the customer chose (or confirmed
    via hint/cascade) must never be silently overridden, even if it now
    disagrees with the recommendation."""
    driver = _attr(1, "isProvisioningRequiredInCloudEnv_astro", "Is provisioning required?",
                    [("YES", "Yes"), ("NO", "No")])
    target = _attr(2, "isFedRampRequired_astro", "Is FedRAMP High Baseline required?",
                    [("YES", "Yes"), ("NO", "No")])
    rule = _rec_rule(1, "YES", 2, "NO")
    filled = {"isProvisioningRequiredInCloudEnv_astro": "YES", "isFedRampRequired_astro": "YES"}

    eng = CpqEngine()
    for source in ("user", "hint", "cascade"):
        corrections = eng.resync_stale_recommendations(
            [driver, target], filled, {"isFedRampRequired_astro": source}, [rule], bml_eval=None,
        )
        assert corrections == {}, f"must not override a {source!r}-sourced value"


def test_resync_no_op_when_already_in_sync():
    driver = _attr(1, "driver_astro", "Driver", [("YES", "Yes")])
    target = _attr(2, "target_astro", "Target", [("NO", "No")])
    rule = _rec_rule(1, "YES", 2, "NO")
    filled = {"driver_astro": "YES", "target_astro": "NO"}  # already correct
    eng = CpqEngine()
    assert eng.resync_stale_recommendations(
        [driver, target], filled, {"target_astro": "auto"}, [rule], bml_eval=None,
    ) == {}


def test_resync_skips_unfilled_targets():
    """An attr with no value yet is apply_recommendation_rules' job, not
    this one's — resync must never be the mechanism that FIRST fills it."""
    driver = _attr(1, "driver_astro", "Driver", [("YES", "Yes")])
    target = _attr(2, "target_astro", "Target", [("NO", "No")])
    rule = _rec_rule(1, "YES", 2, "NO")
    filled = {"driver_astro": "YES"}  # target not filled at all
    eng = CpqEngine()
    assert eng.resync_stale_recommendations(
        [driver, target], filled, {}, [rule], bml_eval=None,
    ) == {}


def test_evaluate_rules_loop_corrects_stale_recommendation_within_one_call():
    """Integration: evaluate_rules_loop's own fixed-point iteration must
    apply this correction, not just the standalone resync method."""
    driver = _attr(1, "isProvisioningRequiredInCloudEnv_astro", "Is provisioning required?",
                    [("YES", "Yes"), ("NO", "No")])
    target = _attr(2, "isFedRampRequired_astro", "Is FedRAMP High Baseline required?",
                    [("YES", "Yes"), ("NO", "No")])
    rule = _rec_rule(1, "YES", 2, "NO")
    filled = {"isProvisioningRequiredInCloudEnv_astro": "YES", "isFedRampRequired_astro": "YES"}
    filled_source = {"isFedRampRequired_astro": "auto", "isProvisioningRequiredInCloudEnv_astro": "user"}

    eng = CpqEngine()
    _attrs, filled_out, _display, _constrained = eng.evaluate_rules_loop(
        [driver, target], hints={}, filled=filled,
        hiding_rules=[], rec_rules=[rule], con_rules=[],
        bml_eval=None, filled_source=filled_source,
    )
    assert filled_out["isFedRampRequired_astro"] == "NO"


def test_evaluate_rules_loop_never_overrides_user_choice_even_if_stale():
    driver = _attr(1, "isProvisioningRequiredInCloudEnv_astro", "Is provisioning required?",
                    [("YES", "Yes"), ("NO", "No")])
    target = _attr(2, "isFedRampRequired_astro", "Is FedRAMP High Baseline required?",
                    [("YES", "Yes"), ("NO", "No")])
    rule = _rec_rule(1, "YES", 2, "NO")
    filled = {"isProvisioningRequiredInCloudEnv_astro": "YES", "isFedRampRequired_astro": "YES"}
    filled_source = {"isFedRampRequired_astro": "user", "isProvisioningRequiredInCloudEnv_astro": "user"}

    eng = CpqEngine()
    _attrs, filled_out, _display, _constrained = eng.evaluate_rules_loop(
        [driver, target], hints={}, filled=filled,
        hiding_rules=[], rec_rules=[rule], con_rules=[],
        bml_eval=None, filled_source=filled_source,
    )
    assert filled_out["isFedRampRequired_astro"] == "YES", (
        "a customer's own choice must survive even when the recommendation now disagrees"
    )
