"""Multi-select coverage for deterministic CPQ validation."""
from __future__ import annotations

from aryx.cpq.state import ConfigAttr, ConstraintRule, MenuOption
from aryx.cpq.validation.models import Scenario
from aryx.cpq.validation.oracle import DeterministicRuleOracle
from aryx.cpq.validation.runner import evaluate_to_fixed_point


def _attr(eid: int, name: str, *values: str) -> ConfigAttr:
    """Build a compact single-select attribute fixture."""
    return ConfigAttr(
        entity_id=eid,
        source_id=eid,
        variable_name=name,
        display_label=name,
        required=False,
        default_value="",
        options=[MenuOption(value, value, order) for order, value in enumerate(values)],
    )


def test_fixed_point_constrains_and_tracks_multi_select_values() -> None:
    """A constrained multi-select stores the complete allowed set separately."""
    condition = _attr(1, "condition", "A")
    target = _attr(2, "target", "X", "Y", "Z")
    target.select_type = "multi"
    constraint = ConstraintRule("allow X Y", 1, "A", 2, ["X", "Y"])
    oracle = DeterministicRuleOracle([condition, target], [], [], [constraint])

    result = evaluate_to_fixed_point(oracle, Scenario("multi", {"condition": "A"}))

    assert result.filled_multi == {"target": ("X", "Y")}


def test_fixed_point_flags_invalid_user_multi_selection() -> None:
    """Explicit disallowed multi values remain visible for human correction."""
    condition = _attr(1, "condition", "A")
    target = _attr(2, "target", "X", "Y")
    target.select_type = "multi"
    constraint = ConstraintRule("allow X", 1, "A", 2, ["X"])
    oracle = DeterministicRuleOracle([condition, target], [], [], [constraint])
    scenario = Scenario(
        "multi-user", {"condition": "A"}, {"condition": "user", "target": "user"},
        {"target": ("X", "Y")},
    )

    result = evaluate_to_fixed_point(oracle, scenario)

    assert any(issue.code == "constraint_user_value" for issue in result.issues)
