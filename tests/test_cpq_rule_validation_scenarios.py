"""CPQ validation scenario coverage and comparison tests."""
from __future__ import annotations

import pytest

from aryx.cpq.state import ConfigAttr, HidingRule, MenuOption
from aryx.cpq.validation.compare import ProductionState, compare_rule_order, compare_states
from aryx.cpq.validation.models import EvaluationResult
from aryx.cpq.validation.scenarios import generate_scenarios


def _attr(eid: int, name: str, *values: str) -> ConfigAttr:
    """Build a compact attribute fixture."""
    return ConfigAttr(
        entity_id=eid,
        source_id=eid,
        variable_name=name,
        display_label=name,
        required=False,
        default_value="",
        options=[MenuOption(value, value, order) for order, value in enumerate(values)],
    )


def test_generate_scenarios_covers_all_attribute_options() -> None:
    """Every selectable option must be seeded by at least one scenario."""
    attrs = [_attr(1, "condition", "A", "B"), _attr(2, "target", "X", "Y")]

    scenarios = generate_scenarios(attrs, [], [], [])
    covered = {(name, value) for scenario in scenarios for name, value in scenario.filled.items()}

    assert covered.issuperset({("condition", "A"), ("condition", "B"),
                               ("target", "X"), ("target", "Y")})


def test_generate_scenarios_expands_tilde_rule_conditions() -> None:
    """Condition literals absent from menus must still receive dedicated scenarios."""
    attrs = [_attr(1, "condition"), _attr(2, "target", "X")]
    rule = HidingRule("tilde", 1, "A~B", 2)

    scenarios = generate_scenarios(attrs, [rule], [], [])
    values = {scenario.filled.get("condition") for scenario in scenarios}

    assert values.issuperset({None, "A", "B"})


def test_compare_states_reports_value_visibility_and_constraint_differences() -> None:
    """The production comparison must expose every rule-loop state dimension."""
    expected = EvaluationResult(
        scenario_id="s1",
        filled={"target": "Y"},
        sources={"target": "rule"},
        hidden=frozenset(),
        constraints={"target": ("Y",)},
        pending=(),
        unknown_rules=(),
        issues=(),
        iterations=2,
        converged=True,
        cycle_detected=False,
    )
    actual = ProductionState(
        filled={"target": "X"},
        visible=frozenset(),
        constraints={"target": ("X",)},
        pending=("target",),
    )

    issues = compare_states(expected, actual, all_attributes={"target"})

    assert {issue.code for issue in issues} == {
        "filled_mismatch", "visibility_mismatch", "constraint_mismatch", "pending_mismatch",
    }


def test_evaluation_result_report_contains_seed_and_iteration_trace() -> None:
    """Every result must carry a minimal reproduction and the pass-by-pass state."""
    expected = EvaluationResult(
        scenario_id="trace",
        filled={},
        sources={},
        hidden=frozenset(),
        constraints={},
        pending=(),
        unknown_rules=(),
        issues=(),
        iterations=1,
        converged=True,
        cycle_detected=False,
        seed={"condition": "A"},
        trace=({"iteration": 1, "filled": {}},),
    )

    rendered = expected.to_dict()

    assert rendered["seed"] == {"condition": "A"} and rendered["trace"][0]["iteration"] == 1


def test_compare_rule_order_reports_order_dependent_production_state() -> None:
    """Shuffling rules must not silently change the production result."""
    first = ProductionState({"target": "X"}, frozenset({"target"}), {}, ())
    reversed_order = ProductionState({}, frozenset(), {}, ("target",))

    issues = compare_rule_order(first, reversed_order)

    assert issues[0].code == "rule_order_dependence"


def test_generate_scenarios_covers_multi_options_in_multi_state() -> None:
    """Multi-select menu options must never be flattened into scalar filled state."""
    multi = _attr(1, "accessories", "A", "B")
    multi.select_type = "multi"

    scenarios = generate_scenarios([multi], [], [], [])
    covered = {values for scenario in scenarios for values in scenario.filled_multi.values()}

    assert covered == {("A",), ("B",)}


def test_generate_scenarios_is_order_independent() -> None:
    """Attribute and rule input order must not change generated seed states."""
    attrs = [_attr(1, "condition", "A", "B"), _attr(2, "target", "X")]
    rules = [HidingRule("z rule", 1, "A", 2), HidingRule("a rule", 1, "B", 2)]

    forward = generate_scenarios(attrs, rules, [], [])
    reversed_input = generate_scenarios(list(reversed(attrs)), list(reversed(rules)), [], [])

    assert forward == reversed_input


def test_generate_scenarios_fails_loudly_at_limit() -> None:
    """Coverage limits must never silently truncate catalog options."""
    attr = _attr(1, "condition", "A", "B")

    with pytest.raises(ValueError, match="scenario limit"):
        generate_scenarios([attr], [], [], [], max_scenarios=1)
