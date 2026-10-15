"""A free-entry quantity the catalog's rules compare to a number is asked.

Flag `cpq_rule_compared_quantity_ask_enabled`. ws 1267, APX N70 (2026-10-15): with a Video RSM chosen, "Qty of SVX
Remote Speaker Mic" is visible, has no options and no validation rule, so it was never asked; the payload went out
without it and MSI's Add Configuration To Transaction
returned "Configuration is incomplete". The catalog's own "Set TRUE if ... > 0" recommendation rule is what marks it a
number field. The fixtures below use made-up names on purpose: the code reads rule shapes, never names."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.cpq.auto_fill import auto_fill_quantity_ask as qa
from aryx.cpq.auto_fill_stages import ask_or_pending, governance_flags
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.state import ConfigAttr, MenuOption, RecommendationRule

QTY, FLAG, PICK = "qtyOfWidget_x", "qtyOfWidgetDummy_x", "widgetColour_x"
GREATER = "5"
EQUALS = "4"


def _attr(vn, eid, *, options=(), hidden=False, select_type="single", source_id=None):
    return ConfigAttr(entity_id=eid, variable_name=vn, display_label=vn, required=False, default_value="",
                      options=[MenuOption(item_value=o, display_name=o) for o in options], hidden=hidden,
                      select_type=select_type, source_id=source_id)


def _rule(cond_id, value="0", operator=GREATER, **kw):
    return RecommendationRule(rule_name="Set TRUE if qty > 0", condition_attr_id=cond_id, condition_value=value,
                              target_attr_id=99, recommended_value="true", condition_operator=operator, **kw)


def _vns(attrs, rules, display_order=None, flag=True):
    with patch.object(qa, "get_settings", return_value=SimpleNamespace(cpq_rule_compared_quantity_ask_enabled=flag)):
        return qa.rule_compared_quantity_vns(attrs, rules, display_order)


def test_a_free_entry_field_a_rule_compares_to_a_number_is_asked():
    assert _vns([_attr(QTY, 1), _attr(FLAG, 99)], [_rule(1)]) == frozenset({QTY})


def test_the_flag_off_changes_nothing():
    assert _vns([_attr(QTY, 1)], [_rule(1)], flag=False) == frozenset()


def test_the_rule_may_name_the_field_by_its_source_id():
    assert _vns([_attr(QTY, 1, source_id=501)], [_rule(501)]) == frozenset({QTY})


def test_a_numeric_operator_inside_a_multi_input_condition_counts():
    rule = _rule(0, value="", operator=EQUALS, conditions=[(7, "YES", EQUALS), (1, "0", GREATER)])
    assert _vns([_attr(QTY, 1), _attr("other_x", 7)], [rule]) == frozenset({QTY})


def test_an_equality_rule_or_a_non_numeric_bound_does_not_make_a_quantity():
    attrs = [_attr(QTY, 1)]
    assert _vns(attrs, [_rule(1, value="0", operator=EQUALS)]) == frozenset()          # "= 0" is a value test
    assert _vns(attrs, [_rule(1, value="ALL", operator=GREATER)]) == frozenset()       # no number to compare to


def test_script_rules_are_not_read():
    assert _vns([_attr(QTY, 1)], [_rule(1, script="if(x > 0){return true;}")]) == frozenset()
    assert _vns([_attr(QTY, 1)], [_rule(1, condition_script="x > 0")]) == frozenset()


def test_fields_with_options_hidden_fields_and_non_scalar_fields_are_never_asked_this_way():
    rules = [_rule(1), _rule(2), _rule(3), _rule(4)]
    attrs = [_attr(PICK, 1, options=("RED", "BLUE")), _attr("hiddenQty_x", 2, hidden=True),
             _attr("multiQty_x", 3, select_type="multi"), _attr("boolQty_x", 4, select_type="boolean")]
    assert _vns(attrs, rules) == frozenset()


def test_a_field_the_loaded_layout_does_not_show_is_not_asked():
    assert _vns([_attr(QTY, 1)], [_rule(1)], display_order={"somethingElse_x": 1}) == frozenset()
    assert _vns([_attr(QTY, 1)], [_rule(1)], display_order={QTY: 3}) == frozenset({QTY})


def test_a_model_without_such_rules_gets_no_extra_question():
    """APX 900 / 4000 shape: rules only test values for equality, so the set stays empty."""
    rules = [_rule(1, value="YES", operator=EQUALS), _rule(2, value="US", operator="3")]
    assert _vns([_attr("a_x", 1), _attr("b_x", 2)], rules) == frozenset()
    assert _vns([_attr(QTY, 1)], None) == frozenset()


def _governance(attr, quantity_vns):
    engine = SimpleNamespace(_is_hardware_version_attr=lambda a: False,
                             _hardware_version_confirmed_not_applicable=lambda *a, **k: True)
    scope = SimpleNamespace(
        base_model_narrowing=None, required_ask_vns=frozenset(), quantity_ask_vns=frozenset(quantity_vns),
        display_order=None, skip_always_ask=None, governed=set(), rule_governed=set(), product_anchor_hint=None,
        workspace_id=1267, catalog_prefix="p", country="US", bm_region_allow_value=None)
    state = AttrResolution(vn=attr.variable_name, vn_flat=attr.variable_name.lower().replace("_", ""))
    governance_flags.stage_governance_flags(engine, attr, SimpleNamespace(dt_cache={}), scope, state)
    return state, scope


def test_the_quantity_becomes_a_decision_attribute_and_others_are_untouched():
    assert _governance(_attr(QTY, 1), {QTY})[0].is_decision_attr is True
    assert _governance(_attr("other_x", 2), {QTY})[0].is_decision_attr is False
    assert _governance(_attr(QTY, 1), set())[0].is_decision_attr is False


def test_the_quantity_lands_in_pending_instead_of_being_left_blank():
    attr = _attr(QTY, 1)
    state, scope = _governance(attr, {QTY})
    scope.grid_selector_vns = set()
    ctx = SimpleNamespace(pending=[])
    engine = SimpleNamespace(_is_noise_var=lambda vn: False, should_ask_free_text_attr=lambda *a: False)
    assert ask_or_pending.resolve_ask_or_pending(engine, attr, ctx, scope, state) is True
    assert ctx.pending == [attr]
