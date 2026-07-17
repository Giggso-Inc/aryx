"""Deterministic CPQ rule-oracle and fixed-point tests."""
from __future__ import annotations

from aryx.cpq.state import ConfigAttr, ConstraintRule, HidingRule, MenuOption
from aryx.cpq.state import RecommendationRule
from aryx.cpq.validation.models import Scenario
from aryx.cpq.validation.oracle import DeterministicRuleOracle
from aryx.cpq.validation.runner import evaluate_to_fixed_point
from aryx.cpq.validation.script_oracle import DeterministicBmlOracle


def _attr(eid: int, name: str, *values: str, default: str = "") -> ConfigAttr:
    """Build a compact single-select attribute fixture."""
    return ConfigAttr(
        entity_id=eid,
        source_id=eid,
        variable_name=name,
        display_label=name,
        required=False,
        default_value=default,
        options=[MenuOption(value, value, order) for order, value in enumerate(values)],
    )


def test_oracle_tilde_condition_matches_every_member() -> None:
    """Every value in a tilde-delimited condition must activate the rule."""
    attrs = [_attr(1, "condition", "A", "B"), _attr(2, "target", "X")]
    rule = HidingRule("hide target", 1, "A~B", 2)
    oracle = DeterministicRuleOracle(attrs, [rule], [], [])

    outcomes = [oracle.evaluate_rules({"condition": value}) for value in ("A", "B")]

    assert all(outcome.hidden == frozenset({"target"}) for outcome in outcomes)


def test_oracle_conflicting_hide_show_is_order_independent() -> None:
    """Conflicting visibility actions must be reported, never list-order resolved."""
    attrs = [_attr(1, "condition", "A"), _attr(2, "target", "X")]
    hide = HidingRule("hide target", 1, "A", 2, hide=True)
    show = HidingRule("show target", 1, "A", 2, hide=False)

    left = DeterministicRuleOracle(attrs, [hide, show], [], []).evaluate_rules({"condition": "A"})
    right = DeterministicRuleOracle(attrs, [show, hide], [], []).evaluate_rules({"condition": "A"})

    assert left == right
    assert any(issue.code == "visibility_conflict" for issue in left.issues)


def test_fixed_point_applies_constraint_before_final_autofill() -> None:
    """A constraint must narrow options before a default can be auto-filled."""
    attrs = [_attr(1, "condition", "A"), _attr(2, "target", "X", "Y", default="X")]
    constraint = ConstraintRule("allow Y", 1, "A", 2, ["Y"])
    oracle = DeterministicRuleOracle(attrs, [], [], [constraint])

    result = evaluate_to_fixed_point(oracle, Scenario("constraint", {"condition": "A"}))

    assert result.filled["target"] == "Y"


def test_fixed_point_preserves_explicit_user_recommendation_override() -> None:
    """Recommendations are advisory for a target explicitly chosen by the user."""
    attrs = [_attr(1, "condition", "A"), _attr(2, "target", "X", "Y")]
    recommendation = RecommendationRule("recommend Y", 1, "A", 2, "Y")
    oracle = DeterministicRuleOracle(attrs, [], [recommendation], [])
    scenario = Scenario(
        "user-override",
        {"condition": "A", "target": "X"},
        {"condition": "user", "target": "user"},
    )

    result = evaluate_to_fixed_point(oracle, scenario)

    assert result.filled["target"] == "X"


def test_fixed_point_detects_self_hiding_cycle() -> None:
    """A self-hiding default must report a cycle instead of hitting a silent cap."""
    target = _attr(1, "target", "X", default="X")
    oracle = DeterministicRuleOracle(
        [target], [HidingRule("self hide", 1, "X", 1)], [], [],
    )

    result = evaluate_to_fixed_point(oracle, Scenario("cycle", {}))

    assert result.cycle_detected is True


def test_unknown_script_is_explicit_in_strict_mode() -> None:
    """Unsupported BML is a coverage failure in strict deterministic mode."""
    attrs = [_attr(1, "target", "X")]
    rule = HidingRule("script hide", 0, "", 1, script="for(i=0;i<2;i++){return true;}")
    oracle = DeterministicRuleOracle(attrs, [rule], [], [])

    result = evaluate_to_fixed_point(oracle, Scenario("script", {}), strict_unknown=True)

    assert any(issue.code == "unknown_script" for issue in result.issues)


def test_source_hidden_default_remains_available_to_rules() -> None:
    """A source-hidden helper stays internally filled while remaining invisible."""
    helper = _attr(1, "helper", default="FLAG")
    helper.hidden = True
    target = _attr(2, "target", "X")
    oracle = DeterministicRuleOracle(
        [helper, target], [HidingRule("hide target", 1, "FLAG", 2)], [], [],
    )

    result = evaluate_to_fixed_point(oracle, Scenario("hidden-default", {}))

    assert result.filled.get("helper") == "FLAG"
    assert result.hidden == frozenset({"helper", "target"})


def test_deterministic_bml_oracle_handles_flat_if_else() -> None:
    """Supported BML executes locally without the production evaluator or LLM."""
    script = 'if (condition == "A") { returnVal = "Y"; } else { returnVal = "X"; }'
    oracle = DeterministicBmlOracle()

    values = (oracle.values(script, {"condition": "A"}),
              oracle.values(script, {"condition": "B"}))

    assert values == (("Y",), ("X",))


def test_supported_script_with_missing_input_is_not_coverage_gap() -> None:
    """A known BML grammar waiting on state must not fail strict coverage."""
    attrs = [_attr(1, "target", "X")]
    script = 'if (condition == "A") { return true; } else { return false; }'
    oracle = DeterministicRuleOracle(
        attrs, [HidingRule("script hide", 0, "", 1, script=script)], [], [],
    )

    result = evaluate_to_fixed_point(oracle, Scenario("missing-input", {}), strict_unknown=True)

    assert not any(issue.code == "unknown_script" for issue in result.issues)


def test_inactive_recommendation_removes_a_stale_rule_value() -> None:
    """A reference pass must not retain a recommendation after it stops firing."""
    attrs = [_attr(1, "condition", "A", "B"), _attr(2, "target", "X", "Y")]
    recommendation = RecommendationRule("recommend Y", 1, "A", 2, "Y")
    oracle = DeterministicRuleOracle(attrs, [], [recommendation], [])
    scenario = Scenario(
        "stale-recommendation",
        {"condition": "B", "target": "Y"},
        {"condition": "user", "target": "rule"},
    )

    result = evaluate_to_fixed_point(oracle, scenario)

    assert "target" not in result.filled
    assert "target" in result.pending
