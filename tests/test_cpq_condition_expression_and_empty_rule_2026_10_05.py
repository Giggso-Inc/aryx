"""Plan F3 (condition_expression over rule_input_index) and F10 (a declarative
rule with no condition rows is always true). Both are flag-gated and must
leave behaviour unchanged when off. All names below are synthetic.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aryx.cpq.bml import bml_declarative as bd
from aryx.cpq.bml.bml_condition_expression import (
    ExprConditions, copy_conditions, evaluate_condition_expression,
)
from aryx.cpq.hiding_rules import apply as hiding_apply
from aryx.cpq.layout_and_join_data import rule_targets
from aryx.cpq.layout_and_join_data.rule_expressions import attach_expressions
from aryx.cpq.state import ConfigAttr, HidingRule


def _cfg(**kw):
    m = MagicMock()
    for k, v in kw.items():
        setattr(m.return_value, k, v)
    return m


def _expr(expression, rows):
    """rows: list of (index, attr_id, value, operator)."""
    return ExprConditions([(a, v, o) for _i, a, v, o in rows], expression, [i for i, *_ in rows])


ROWS = [(1, 10, "A", "4"), (2, 20, "B", "4"), (3, 30, "C", "4"), (4, 40, "D", "4")]


def test_and_binds_tighter_than_or_and_parentheses_group():
    cond = _expr("1 AND 2 OR 3", ROWS)
    assert evaluate_condition_expression(cond, {10: "A", 20: "x", 30: "C"}) == (True, False)
    assert evaluate_condition_expression(cond, {10: "A", 20: "x", 30: "x"}) == (False, False)
    grouped = _expr("1 AND (2 OR 3)", ROWS)
    assert evaluate_condition_expression(grouped, {10: "A", 20: "x", 30: "C"}) == (True, False)
    assert evaluate_condition_expression(grouped, {10: "x", 20: "B", 30: "C"}) == (False, False)


def test_unknown_only_decides_when_no_known_operand_does():
    cond = _expr("1 AND 2", ROWS)
    assert evaluate_condition_expression(cond, {10: "x"}) == (False, False)       # a known False decides
    assert evaluate_condition_expression(cond, {10: "A"}) == (None, True)         # 2 unknown
    either = _expr("1 OR 2", ROWS)
    assert evaluate_condition_expression(either, {10: "A"}) == (True, False)      # a known True decides
    assert evaluate_condition_expression(either, {10: "x"}) == (None, True)


def test_different_operators_on_one_attribute_are_evaluated_per_row():
    """`< 1 OR > 12` on the same attribute (the collision case the grouping cannot handle)."""
    cond = _expr("1 OR 2", [(1, 10, "1", "1"), (2, 10, "12", "5")])
    assert evaluate_condition_expression(cond, {10: "0"}) == (True, False)
    assert evaluate_condition_expression(cond, {10: "13"}) == (True, False)
    assert evaluate_condition_expression(cond, {10: "5"}) == (False, False)


def test_unsupported_expression_raises():
    for bad in ("1 AND", "(1 OR 2", "1 XOR 2", "1 2", "9"):
        with pytest.raises(ValueError):
            evaluate_condition_expression(_expr(bad, ROWS), {10: "A", 20: "B"})


def test_declarative_conditions_use_the_expression_only_when_the_flag_is_on():
    cond = _expr("1 AND 2 OR 3", ROWS)
    filled = {10: "x", 20: "x", 30: "C"}          # expression: True; attribute grouping: 3 distinct attrs, all must match
    with patch.object(bd, "get_settings", _cfg(cpq_condition_expression_enabled=True)):
        assert bd.evaluate_declarative_conditions(cond, filled) == (True, False)
    with patch.object(bd, "get_settings", _cfg(cpq_condition_expression_enabled=False)):
        assert bd.evaluate_declarative_conditions(cond, filled) == (False, False)
    with patch.object(bd, "get_settings", _cfg(cpq_condition_expression_enabled=True)):
        bad = _expr("1 AND", ROWS)                  # unsupported -> falls back to attribute grouping
        assert bd.evaluate_declarative_conditions(bad, {10: "A", 20: "B", 30: "C", 40: "D"}) == (True, False)


def test_copy_conditions_keeps_the_expression():
    cond = _expr("1 OR 2", ROWS)
    dup = copy_conditions(cond)
    assert isinstance(dup, ExprConditions) and dup.expression == "1 OR 2" and dup.indexes == cond.indexes and dup is not cond
    plain = [(1, "a", "4")]
    assert copy_conditions(plain) == plain and not isinstance(copy_conditions(plain), ExprConditions)


def test_attach_expressions_matches_rows_to_indexes_and_leaves_mismatches_plain():
    rdb = MagicMock()
    rdb.fetch_rule_condition_expressions.return_value = {7: "1 OR 2", 8: "1 AND 2"}
    rdb.fetch_rule_input_indexes.return_value = [
        (7, 10, "A", "4", 2), (7, 20, "B", "4", 1),               # same rows, other order than the plain fetch
        (8, 10, "A", "4", 1),                                     # rule 8 has 2 plain rows but 1 indexed row
    ]
    plain = {7: [(10, "A", "4"), (20, "B", "4")], 8: [(10, "A", "4"), (30, "C", "4")], 9: [(40, "D", "4")]}
    out = attach_expressions(rdb, 1, "", plain)
    assert isinstance(out[7], ExprConditions) and out[7].indexes == [2, 1] and list(out[7]) == plain[7]
    assert not isinstance(out[8], ExprConditions) and out[8] == plain[8]
    assert out[9] == plain[9]
    rdb.fetch_rule_condition_expressions.return_value = {}
    assert attach_expressions(rdb, 1, "", plain) is plain


def test_operator_collision_is_skipped_only_for_expression_rules_with_the_flag_on():
    same_attr = [(10, "1", "1"), (10, "12", "5")]
    assert rule_targets._condition_has_operator_collision(same_attr) is True
    cond = ExprConditions(same_attr, "1 OR 2", [1, 2])
    with patch.object(rule_targets, "get_settings", _cfg(cpq_condition_expression_enabled=True)):
        assert rule_targets._condition_has_operator_collision(cond) is False
    with patch.object(rule_targets, "get_settings", _cfg(cpq_condition_expression_enabled=False)):
        assert rule_targets._condition_has_operator_collision(cond) is True


# ── F10 ───────────────────────────────────────────────────────────────────

def _attr(eid, vn):
    return ConfigAttr(entity_id=eid, variable_name=vn, display_label=vn, required=False, default_value="", options=[])


def test_a_hiding_rule_without_conditions_hides_only_when_marked_always():
    attrs = [_attr(1, "target_vn")]
    always = HidingRule(rule_name="r", condition_attr_id=0, condition_value="", target_attr_id=1, always=True)
    plain = HidingRule(rule_name="r", condition_attr_id=0, condition_value="", target_attr_id=1)
    shown, _msgs, hidden = hiding_apply.apply_hiding_rules(attrs, {}, [always])
    assert hidden == {"target_vn"} and shown == []
    shown, _msgs, hidden = hiding_apply.apply_hiding_rules(attrs, {}, [plain])
    assert hidden == set() and len(shown) == 1


def test_hiding_rule_always_defaults_to_false():
    assert HidingRule(rule_name="r", condition_attr_id=1, condition_value="x", target_attr_id=2).always is False
