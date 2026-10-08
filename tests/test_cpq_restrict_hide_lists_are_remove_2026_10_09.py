"""Restrict.../Hide... declarative `set_type -1` lists are the values taken away (flag
`cpq_restrict_hide_lists_are_remove_enabled`).

ws 1267, APX 4000: 'Restrict Frequency Band except 900MHz' lists VHF, 700/800, UHF R1, UHF R2, 8/900. Loaded as an allow-list it
offered exactly those bands and left out 900 MHz, the only band the real screen offers."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.cpq.constraint_rules import constraint_rules_mode as mode
from aryx.cpq.state import ConstraintRule, MenuOption
from aryx.cpq.value_rules import value_rules_finalize as fin

BANDS = ["VHF", "700/800 MHZ", "UHF R1", "UHF R2", "900 MHZ"]


def _target(values):
    return SimpleNamespace(options=[MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, 1)])


def _rule(values, remove_list=True, name="Restrict Frequency Band except 900MHz"):
    return ConstraintRule(rule_name=name, condition_attr_id=1, condition_value="APX4000", target_attr_id=2,
                          allowed_values=list(values), remove_list=remove_list)


def _settings(flag):
    return patch.object(fin, "get_settings", return_value=SimpleNamespace(
        cpq_restrict_hide_lists_are_remove_enabled=flag))


def test_the_frequency_rule_leaves_only_900_mhz_as_a_remove_list():
    rule = _rule(["VHF", "700/800 MHZ", "UHF R1", "UHF R2", "8/900 MHZ"])
    assert mode.effective_allowed(rule, _target(BANDS)) == ["900 MHZ"]


def test_today_the_same_list_is_an_allow_list_and_offers_the_wrong_bands():
    rule = _rule(["VHF", "700/800 MHZ", "UHF R1", "UHF R2", "8/900 MHZ"], remove_list=False)
    assert mode.effective_allowed(rule, _target(BANDS)) == ["VHF", "700/800 MHZ", "UHF R1", "UHF R2", "8/900 MHZ"]


def test_matching_ignores_case_and_spacing():
    assert mode.effective_allowed(_rule(["vhf ", " uhf r1"]), _target(BANDS)) == ["700/800 MHZ", "UHF R2", "900 MHZ"]


def test_quantity_or_number_lists_keep_the_old_reading():
    rule = _rule(["1000"], name="Restrict Max Qty")
    assert mode.effective_allowed(rule, _target(["1", "2", "3"])) == ["1000"]       # nothing matches an option
    assert mode.effective_allowed(rule, SimpleNamespace(options=[])) == ["1000"]    # a free-text / numeric attribute


def test_a_list_that_would_empty_the_attribute_keeps_the_old_reading():
    rule = _rule(BANDS, name="Hide other Keypad Language when Arabic Control Selected")
    assert mode.effective_allowed(rule, _target(BANDS)) == BANDS


def test_a_constrain_rule_and_the_english_only_rule_stay_allow_lists():
    rule = _rule(["ENGLISH"], remove_list=False, name="Constraint All the Language Type options except English if Made In America is Yes")
    assert mode.effective_allowed(rule, _target(["ENGLISH", "ARABIC", "HEBREW"])) == ["ENGLISH"]


def test_the_loader_marks_only_restrict_and_hide_rules_and_only_with_the_flag():
    with _settings(True):
        assert fin._remove_list_by_name("Restrict Frequency Band except 900MHz") is True
        assert fin._remove_list_by_name("hide other Keypad Language") is True
        assert fin._remove_list_by_name("INACTIVE: Restrict LOCALIZED ENABLED") is False
        assert fin._remove_list_by_name("Constrain Antenna Type for Single Band") is False
        assert fin._remove_list_by_name("Constraint Site Router, Except Region NA") is False
    with _settings(False):
        assert fin._remove_list_by_name("Restrict Frequency Band except 900MHz") is False
    with patch.object(fin, "get_settings", return_value=object()):
        assert fin._remove_list_by_name("Restrict Frequency Band except 900MHz") is False


def test_finalize_builds_the_rule_with_the_marker():
    state = SimpleNamespace(con_rules=[], rec_rules=[], hiding_rules=[], script_condition_gated=0, cond_script_skipped=0,
                            constraint_collisions_skipped=0, recommendation_collisions_skipped=0, hiding_collisions_skipped=0)
    with _settings(True):
        fin.finalize_rule_actions(state, 1, "Restrict Frequency Band except 900MHz", -1, None, 5, "APX4000", "4", [(5, "APX4000", "4")],
                                  {7: ["VHF", "UHF R1"]}, {}, set(), False)
    assert [r.remove_list for r in state.con_rules] == [True]
