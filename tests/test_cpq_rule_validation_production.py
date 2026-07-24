"""Read-only production-adapter tests for CPQ deterministic validation."""
from __future__ import annotations

from typing import Any

from aryx.cpq.state import ConfigAttr, MenuOption
from aryx.cpq.validation.models import Scenario
from aryx.cpq.validation.production import evaluate_production


def _attr(eid: int, name: str) -> ConfigAttr:
    """Build a compact attribute fixture."""
    return ConfigAttr(
        entity_id=eid,
        variable_name=name,
        display_label=name,
        required=False,
        default_value="",
        options=[MenuOption("A", "A", 1)],
    )


class _MutatingEngine:
    """Engine double that aggressively mutates every supplied state object."""

    def evaluate_rules_loop(
        self, attrs: list[ConfigAttr], _hints: dict[str, str], filled: dict[str, str],
        *_rules: Any, filled_source: dict[str, str],
        filled_multi: dict[str, list[str]], **_kwargs: Any,
    ) -> tuple[list[ConfigAttr], dict[str, str], dict[str, str], dict[int, list[str]]]:
        """Mutate copies so the test can prove caller-owned inputs are isolated."""
        attrs.pop()
        filled["generated"] = "A"
        filled_source["generated"] = "rule"
        filled_multi.setdefault("multi", []).append("B")
        return attrs, filled, {}, {}

    @staticmethod
    def governed_target_ids(*_args: Any) -> set[int]:
        """Return no governed targets for the fake state."""
        return set()

    @staticmethod
    def rule_governed_ids(*_args: Any) -> set[int]:
        """Return no strictly rule-governed targets for the fake state."""
        return set()

    @staticmethod
    def auto_fill(
        attrs: list[ConfigAttr], *_args: Any, **_kwargs: Any,
    ) -> tuple[dict[str, str], dict[str, str], list[ConfigAttr]]:
        """Return no pending values; mutation behavior is tested above."""
        return {}, {}, []


def test_evaluate_production_never_mutates_scenario_or_attribute_list() -> None:
    """Production comparison must isolate every caller-owned input container."""
    attrs = [_attr(1, "condition"), _attr(2, "target")]
    scenario = Scenario(
        "read-only", {"condition": "A"}, {"condition": "user", "multi": "user"},
        {"multi": ("A",)},
    )

    state = evaluate_production(_MutatingEngine(), attrs, scenario, [], [], [], object())

    assert scenario.filled == {"condition": "A"} and len(attrs) == 2
    assert scenario.filled_multi == {"multi": ("A",)}
    assert state.filled_multi == {"multi": ("A", "B")}
