"""Diagnostic logs for two dev findings (2026-10-09): Encryption Type hidden by a master-string rule, and a rule writing a
part-number-shaped value into the base model (N50 `TT2592A`). Logging only: none of these changes a result."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.cpq.hiding_rules import unknown_log
from aryx.cpq.payload_building import required_set as rs
from aryx.cpq.recommendation_and_constraint_rules import base_model_rule_log as bml
from aryx.cpq.state import ConfigAttr

ENC = "secureEncryptionType_astro"


def _attr(eid, vn, hidden=False, hide_in_trans=False):
    return ConfigAttr(entity_id=eid, variable_name=vn, display_label=vn, required=False, default_value="",
                      select_type="single", hidden=hidden, options=[], hide_in_trans=hide_in_trans)


# --- base-model rule value ---------------------------------------------------------------------------------------------
def _rule(name="Set Base Model"):
    return SimpleNamespace(rule_name=name, ref_id="39185800", conditions=[(11, "APX N50", "4")], condition_attr_id=11,
                           condition_value="APX N50", condition_script=None, script=None)


def test_value_shape_maps_letters_and_digits_by_class():
    assert bml.value_shape("H25UCF9PW6AN") == "A99AAA9AA9AA"
    assert bml.value_shape("TT2592A") == "AA9999A"


def test_a_base_model_value_of_a_different_shape_is_a_warning_with_the_rule_name():
    with patch.object(bml, "raven_log") as log, \
            patch("aryx.cpq.auto_fill_stages.fill_log.is_base_model_vn", return_value=True):
        bml.log_base_model_rule_value(_rule(), "modelSelectionbaseModel_astro", "TT2592A", "H25UCF9PW6AN", "resync")
    level, _, message = log.call_args.args[:3]
    ctx = log.call_args.kwargs["context"]
    assert level == "WARN" and "different shape" in message
    assert ctx["rule_name"] == "Set Base Model" and ctx["shape_recommended"] == "AA9999A" and ctx["condition_values"] == ["APX N50"]


def test_a_value_of_the_same_shape_is_only_a_debug_record_and_other_attributes_are_ignored():
    with patch.object(bml, "raven_log") as log, \
            patch("aryx.cpq.auto_fill_stages.fill_log.is_base_model_vn", return_value=True):
        bml.log_base_model_rule_value(_rule(), "modelSelectionbaseModel_astro", "H15UCF9PW6AN", "H25UCF9PW6AN", "resync")
    assert log.call_args.args[0] == "DEBUG"
    with patch.object(bml, "raven_log") as log, \
            patch("aryx.cpq.auto_fill_stages.fill_log.is_base_model_vn", return_value=False):
        bml.log_base_model_rule_value(_rule(), "antennasType_astro", "X", "Y", "resync")
    assert not log.called


# --- required set ------------------------------------------------------------------------------------------------------
def test_the_invisible_reason_follows_the_order_of_the_visibility_checks():
    assert rs._invisible_reason(_attr(1, "a", hidden=True), set(), None) == "catalog_hidden"
    assert rs._invisible_reason(_attr(1, "a", hide_in_trans=True), set(), None) == "hide_in_trans"
    assert rs._invisible_reason(_attr(1, "a"), {"a"}, None) == "hidden_by_rule"
    assert rs._invisible_reason(_attr(1, "a"), set(), {"b": 1}) == "not_in_layout"


def test_the_rule_stats_count_what_was_loaded_and_what_fired():
    rule = SimpleNamespace(mode="DISALLOW", blank=True, condition_script=None, guard_attr="", target_attr_id=3,
                           conditions=[(2, "", "3")])
    unfired = SimpleNamespace(mode="DISALLOW", blank=True, condition_script=None, guard_attr="", target_attr_id=3,
                              conditions=[(2, "NOPE", "4")])
    engine = SimpleNamespace(load_recommendation_and_constraint_rules=lambda *a, **k: ([], [rule, unfired]),
                             load_validation_rules=lambda *a, **k: [])
    attrs = [_attr(2, "baseModel"), _attr(3, ENC)]
    stats: dict = {}
    with patch.object(rs, "get_settings", return_value=SimpleNamespace(cpq_required_set_guards_assumed_open=False)):
        found = rs.rule_required_vns(engine, attrs, {"baseModel": "M37"}, {}, 1267, "p", None, stats)
    assert found == {ENC}
    assert stats["blank_disallow_loaded"] == 2 and stats["blank_disallow_condition_fired"] == 1
    assert stats["validation_loaded"] == 0 and stats["assumed_master_strings"] == 0


def test_the_diagnostic_lists_why_a_candidate_was_dropped():
    with patch("aryx.raven_log.would_log", return_value=True), patch("aryx.raven_log.raven_log") as log:
        rs._log_required_set_diagnostic(rule_only=True, stats={"blank_disallow_loaded": 5}, found={ENC, "x"},
                                        dropped={ENC: "hidden_by_rule", "x": "not_in_attribute_list"}, kept=set(),
                                        models=["APX900"], base_model="H92", attr_count=40)
    ctx = log.call_args.kwargs["context"]
    assert ctx["dropped"][ENC] == "hidden_by_rule" and ctx["blank_disallow_loaded"] == 5 and ctx["base_known"] is True


# --- master-string context ---------------------------------------------------------------------------------------------
def test_the_master_context_says_whether_the_target_is_in_the_computed_master_string():
    rule = SimpleNamespace(rule_name="Hide Secure Attributes If No Values Available (Mobile)", ref_id="1")
    decided = {"master_var": "hiddenMasterString", "cpq_model": "APXN30", "base_models": ["H15UCF9PW6AN"], "master_names": 2,
               "master_len": 40, "live_writers": 1, "_names": {"antennasType_astro", "batteryType_astro"}}
    with patch.object(unknown_log, "would_log", return_value=True), patch.object(unknown_log, "raven_log") as log, \
            patch.object(unknown_log, "get_run_id", return_value="run-ctx-1"):
        unknown_log.log_master_context(rule, ENC, decided, True)
        unknown_log.log_master_context(rule, ENC, decided, True)       # once per (run, rule, target, outcome)
    assert log.call_count == 1
    ctx = log.call_args.kwargs["context"]
    assert ctx["target_in_master"] is False and ctx["cpq_model"] == "APXN30" and ctx["selected_option"] == "hide"


def test_the_assumed_master_string_count_counts_attributes_not_ids():
    both_ids = ConfigAttr(entity_id=1, variable_name="hiddenConstraintMasterString_astro", display_label="m", required=False,
                          default_value="", select_type="single", hidden=True, options=[], source_id=1001)
    one_id = ConfigAttr(entity_id=2, variable_name="hiddenOtherMasterString_astro", display_label="m", required=False,
                        default_value="", select_type="single", hidden=True, options=[])      # no source id
    with patch.object(rs, "get_settings", return_value=SimpleNamespace(cpq_required_set_master_string_present_enabled=True)):
        assert len(rs._assumed_master_string_attrs([both_ids, one_id], {}, {})) == 2
        assert len(rs._assumed_master_strings([both_ids, one_id], {}, {})) == 3        # ids: 1 + 1001 + 2
