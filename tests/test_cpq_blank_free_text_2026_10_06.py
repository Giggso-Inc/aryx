"""Flag `cpq_blank_free_text_in_conditions_enabled`: a condition script sees unfilled
free-text attributes as "" (BML's reading of unset text). Synthetic names only."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.cpq.constraint_rules import constraint_rules_apply as cra
from aryx.cpq.constraint_rules import constraint_rules_blank_text as bt
from aryx.cpq.state import ConfigAttr, ConstraintRule, MenuOption


def _cfg(flag):
    m = MagicMock()
    m.return_value.cpq_blank_free_text_in_conditions_enabled = flag
    return m


def _attr(eid, vn, options=(), select_type="single"):
    opts = [MenuOption(item_value=o, display_name=o, order=i) for i, o in enumerate(options)]
    return ConfigAttr(entity_id=eid, variable_name=vn, display_label=vn, required=False,
                      default_value="", options=opts, select_type=select_type)


ATTRS = [_attr(1, "freeText"), _attr(2, "menuAttr", ("A", "B")), _attr(3, "multiAttr", select_type="multi"),
         _attr(4, "answered")]


def test_only_unfilled_free_text_attributes_become_empty_strings():
    with patch.object(bt, "get_settings", _cfg(True)):
        out = bt.with_blank_free_text(ATTRS, {"answered": "x"})
    assert out == {"answered": "x", "freeText": ""}


def test_flag_off_returns_the_same_dict():
    filled = {"answered": "x"}
    with patch.object(bt, "get_settings", _cfg(False)):
        assert bt.with_blank_free_text(ATTRS, filled) is filled


def test_apply_rules_passes_the_blank_aware_variables_to_condition_scripts():
    seen = {}

    class Checker:
        def condition_holds(self, script, variables):
            seen["vars"] = dict(variables)
            return True

    target = _attr(5, "t_vn", ("YES", "NO"))
    rule = ConstraintRule(rule_name="r", condition_attr_id=0, condition_value="", target_attr_id=5,
                          allowed_values=["YES"], condition_script="s")
    constrained, contributions = {}, {}
    cra.apply_rules([rule], {5: target}, {}, {}, Checker(), 1, "", None, constrained, contributions,
                    condition_vars={"freeText": ""})
    assert seen["vars"] == {"freeText": ""} and constrained == {5: ["YES"]}
