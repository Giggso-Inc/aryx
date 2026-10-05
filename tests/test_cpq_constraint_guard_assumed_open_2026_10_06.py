"""A DISALLOW action inside `if(<session var> <> "")` applies when flag
`cpq_required_set_guards_assumed_open` is on and the quote does not carry that
variable (the host sets it in production). Synthetic names only."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.cpq.constraint_rules import constraint_rules_apply as cra
from aryx.cpq.constraint_rules.constraint_rules_mode import guard_open
from aryx.cpq.state import ConfigAttr, ConstraintRule, MenuOption


def _cfg(flag):
    m = MagicMock()
    m.return_value.cpq_required_set_guards_assumed_open = flag
    return m


TARGET = ConfigAttr(
    entity_id=5, variable_name="housing", display_label="Housing", required=False, default_value="",
    options=[MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(("GREEN", "SPECIAL PACKAGE"))],
)
# condition: product (id 9) <> "MODEL-S"; action: DISALLOW "SPECIAL PACKAGE" behind guard "sessionVar"
RULE = ConstraintRule(
    rule_name="special package only on MODEL-S", condition_attr_id=0, condition_value="", target_attr_id=5,
    allowed_values=["SPECIAL PACKAGE"], mode="DISALLOW", guard_attr="sessionVar",
    conditions=[(9, "MODEL-S", "3")],
)


def _apply(flag, filled):
    constrained, contributions = {}, {}
    with patch.object(cra, "get_settings", _cfg(flag)):
        cra.apply_rules([RULE], {5: TARGET}, filled, {9: "MODEL-X"}, None, 1, "", None,
                        constrained, contributions)
    return constrained


def test_guard_assumed_open_only_for_a_variable_the_quote_does_not_carry():
    assert guard_open(RULE, {}, assume_open=True) is True
    assert guard_open(RULE, {"sessionVar": ""}, assume_open=True) is False
    assert guard_open(RULE, {}, assume_open=False) is False
    assert guard_open(RULE, {"sessionVar": "X"}) is True


def test_the_disallowed_value_is_removed_when_the_flag_is_on():
    assert _apply(True, {}) == {5: ["GREEN"]}


def test_flag_off_keeps_the_old_behaviour():
    assert _apply(False, {}) == {}
