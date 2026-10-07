"""A script-backed recommendation rule keeps its own declarative inputs as `conditions` (flag-gated), so the
master-string writer test can decide whether the writer fires. ws 1267: "Set Hidden Master String For Astro
Portable" has one input (attribute NOT BLANK, operator 3) and no condition function."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import aryx.cpq.value_rules.value_rules_script_actions as vsa
from aryx.cpq.hiding_rules.master_string import writer_fires
from aryx.cpq.recommendation_and_constraint_rules.rule_condition import resolve_recommended_value

WRITER_SCRIPT = 'x = "a";\nreturn x;'
INPUTS = [(39426962, "", "3")]                                   # attribute not blank


def _cfg(on: bool):
    s = MagicMock()
    s.return_value = SimpleNamespace(cpq_constraint_mode_enabled=False, cpq_script_rec_rule_conditions_enabled=on)
    return s


def _load(on: bool, inputs=INPUTS):
    state = SimpleNamespace(con_rules=[], rec_rules=[], script_constraints=0, script_recommendations_wired=0)
    with patch.object(vsa, "get_settings", _cfg(on)):
        vsa.process_script_backed_actions(None, state, 9, "writer", -1, inputs, [(5, 0, "", 77, 3, "")],
                                          {77: WRITER_SCRIPT})
    assert len(state.rec_rules) == 1
    return state.rec_rules[0]


def test_flag_off_keeps_the_old_shape_and_the_writer_stays_undecided():
    rule = _load(False)
    assert rule.conditions is None and rule.condition_attr_id == 0
    assert writer_fires(rule, {39426962: "x"}, {}) is None


def test_flag_on_keeps_the_inputs_so_the_writer_condition_is_decided():
    rule = _load(True)
    assert list(rule.conditions) == INPUTS
    assert writer_fires(rule, {39426962: "PORTABLE"}, {}) is True        # not blank -> fires
    assert writer_fires(rule, {39426962: ""}, {}) is False               # blank -> the master string is empty


def test_a_rule_without_inputs_is_unchanged():
    assert _load(True, inputs=None).conditions is None


def test_when_the_rule_itself_fires_does_not_change():
    """The applier reads `script` first for a script-backed rule and never consults `conditions`."""
    for on in (False, True):
        rule = _load(on)
        bml = MagicMock()
        bml.allowed_values_for_script.return_value = ["v"]
        assert resolve_recommended_value(rule, {}, {39426962: ""}, bml) == "v"
