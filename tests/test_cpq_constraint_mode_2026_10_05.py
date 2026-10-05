"""Plan F2: the ALLOW/DISALLOW mode of a `setConstraintValuesInSession` action.
Flag-gated (`cpq_constraint_mode_enabled`); synthetic names only.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aryx.cpq.constraint_rules import constraint_rules_apply as cra
from aryx.cpq.constraint_rules.constraint_rules_mode import effective_allowed, guard_open
from aryx.cpq.state import ConfigAttr, ConstraintRule, MenuOption
from aryx.cpq.value_rules import value_rules_script_actions as vsa
from aryx.cpq.value_rules.value_rules_constraint_mode import parse_constraint_mode


def _cfg(**kw):
    m = MagicMock()
    for k, v in kw.items():
        setattr(m.return_value, k, v)
    return m


GUARDED = '''
retVal = "NO";
if(someSessionVar <> ""){
    setValResp = util.setConstraintValuesInSession("targetAttr", retVal, "DISALLOW"+"_"+ someSessionVar);
}
return retVal;
'''
LIST = 'vals = string[]{"A","B|^|C"}; x = util.setConstraintValuesInSession("t", vals, "ALLOW");'
INLINE = 'util.setConstraintValuesInSession("t", "ONLY~TWO", "DISALLOW");'


def test_parse_reads_mode_literal_list_and_guard_from_the_script():
    p = parse_constraint_mode(GUARDED)
    assert (p.mode, p.values, p.guard_var) == ("DISALLOW", ["NO"], "someSessionVar")
    q = parse_constraint_mode(LIST)
    assert (q.mode, q.values, q.guard_var) == ("ALLOW", ["A", "B", "C"], "")
    r = parse_constraint_mode(INLINE)
    assert (r.mode, r.values) == ("DISALLOW", ["ONLY", "TWO"])


def test_parse_ignores_commented_calls_and_non_literal_lists():
    assert parse_constraint_mode('// util.setConstraintValuesInSession("t", "X", "ALLOW");') is None
    assert parse_constraint_mode('v = someFunction(); util.setConstraintValuesInSession("t", v, "ALLOW");') is None
    assert parse_constraint_mode("return 1;") is None and parse_constraint_mode(None) is None


def _target():
    opts = [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(("YES", "NO", "MAYBE"))]
    return ConfigAttr(entity_id=5, variable_name="t_vn", display_label="T", required=False, default_value="", options=opts)


def test_effective_allowed_and_guard():
    allow = ConstraintRule(rule_name="r", condition_attr_id=1, condition_value="", target_attr_id=5, allowed_values=["YES"])
    dis = ConstraintRule(rule_name="r", condition_attr_id=1, condition_value="", target_attr_id=5,
                         allowed_values=["no"], mode="DISALLOW", guard_attr="g")
    assert effective_allowed(allow, _target()) == ["YES"]
    assert effective_allowed(dis, _target()) == ["YES", "MAYBE"]          # case-insensitive removal
    assert guard_open(dis, {"g": "X"}) is True
    assert guard_open(dis, {"g": " "}) is False and guard_open(dis, {}) is False
    assert guard_open(allow, {}) is True


def _apply(rule, filled_by_rule_id, filled):
    constrained, contributions = {}, {}
    cra.apply_rules([rule], {5: _target()}, filled, filled_by_rule_id, None, None, "", None, constrained, contributions)
    return constrained


def test_apply_rules_removes_disallowed_values_when_conditions_hold_and_guard_is_open():
    rule = ConstraintRule(rule_name="r", condition_attr_id=1, condition_value="", target_attr_id=5, allowed_values=["NO"],
                          conditions=[(1, "BR", "4")], mode="DISALLOW", guard_attr="g")
    assert _apply(rule, {1: "BR"}, {"g": "x"}) == {5: ["YES", "MAYBE"]}
    assert _apply(rule, {1: "BR"}, {}) == {}                    # guard variable empty: the call would not run
    assert _apply(rule, {1: "US"}, {"g": "x"}) == {}            # condition false


def test_loader_builds_a_mode_rule_only_when_the_flag_is_on():
    inp = [(1, "BR", "4"), (2, "YES", "3")]
    for flag, expect_mode in ((True, "DISALLOW"), (False, None)):
        state = SimpleNamespace(con_rules=[], rec_rules=[], script_constraints=0, script_recommendations_wired=0)
        with patch.object(vsa, "get_settings", _cfg(cpq_constraint_mode_enabled=flag)):
            vsa.process_script_backed_actions(
                None, state, 9, "rule", -1, inp, [(5, 0, "", 77, -1, "")], {77: GUARDED})
        assert len(state.con_rules) == 1
        rule = state.con_rules[0]
        if expect_mode:
            assert (rule.mode, rule.allowed_values, rule.guard_attr, rule.script) == ("DISALLOW", ["NO"], "someSessionVar", None)
            assert list(rule.conditions) == inp
        else:
            assert rule.mode == "" and rule.script == GUARDED         # legacy script-backed rule
