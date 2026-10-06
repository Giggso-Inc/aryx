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
    assert out == {"answered": "x", "freeText": "", "multiAttr": ""}


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


def test_a_declarative_not_equal_condition_on_an_unfilled_free_text_attribute_fires_with_the_flag():
    from aryx.cpq.bml.bml import evaluate_declarative_conditions
    from aryx.cpq.hiding_rules.attr_index import _filled_by_rule_id

    conditions = [(1, "SOME-ID", "3")]                 # free-text attribute 1 <> "SOME-ID"
    with patch.object(bt, "get_settings", _cfg(True)):
        on = _filled_by_rule_id(ATTRS, bt.with_blank_free_text(ATTRS, {}))
    with patch.object(bt, "get_settings", _cfg(False)):
        off = _filled_by_rule_id(ATTRS, bt.with_blank_free_text(ATTRS, {}))
    assert evaluate_declarative_conditions(conditions, on)[0] is True
    assert evaluate_declarative_conditions(conditions, off)[0] is None


def test_an_unselected_multi_select_attribute_reads_as_empty_and_a_selected_one_keeps_its_choice():
    with patch.object(bt, "get_settings", _cfg(True)):
        out = bt.with_blank_free_text(ATTRS, {}, {"multiAttr": []})
        kept = bt.with_blank_free_text(ATTRS, {}, {"multiAttr": ["x"]})
    assert out["multiAttr"] == "" and "multiAttr" not in kept


def test_a_recommendation_script_with_a_find_on_an_untouched_multi_select_resolves():
    from aryx.cpq.bml import bml_branches as bb, bml_find as bf
    from aryx.cpq.bml import bml_tier1
    from aryx.cpq.recommendation_and_constraint_rules import apply_recommendations as ar
    from aryx.cpq.state import RecommendationRule

    script = ('if(zone=="N"){ return "NO"; } '
              'if(find(features,"TRIGGER") > -1){ return "NO"; } else { return "YES"; }')
    attrs = [_attr(1, "zone", ("N", "E")), _attr(2, "features", select_type="multi"), _attr(3, "guide", ("YES", "NO"))]
    rule = RecommendationRule(rule_name="r", condition_attr_id=0, condition_value="", target_attr_id=3, script=script)
    class Checker:
        def allowed_values_for_script(self, text, variables):
            return bml_tier1.evaluate_tier1(text, variables)[0]

    def run(flag):
        with patch.object(bt, "get_settings", _cfg(flag)),                 patch.object(bb, "find_enabled", lambda: True), patch.object(bf, "find_enabled", lambda: True):
            return ar.apply_recommendation_rules(attrs, {"zone": "E"}, [rule], Checker(), {})

    assert run(True) == {"guide": ("YES", "YES")}
    assert run(False) == {}
