"""Hidden MasterString attributes count as non-blank for the required set (flag `cpq_required_set_master_string_present_enabled`).

ws 1267: 'Restrict blank value for Encryption Type for US or FED customers' needs hiddenConstraintMasterString_astro <> '' (and 73
other rules use it); real CPQ fills the string from rules, the engine never does, so Encryption Type was never required."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.cpq.payload_building import required_set as rs
from aryx.cpq.state import ConfigAttr

MASTER = "hiddenConstraintMasterString_astro"
ENC = "secureEncryptionType_astro"


def _attr(eid, vn, hidden=False, options=()):
    return ConfigAttr(entity_id=eid, variable_name=vn, display_label=vn, required=False, default_value="",
                      select_type="single", hidden=hidden, options=list(options), source_id=eid + 1000)


ATTRS = [_attr(1, MASTER, hidden=True), _attr(2, "baseModel"), _attr(3, ENC),
         _attr(4, "pdKey_astro", hidden=True), _attr(5, "modelSelectionRegion_astro", hidden=True),
         _attr(6, "hiddenWithOptionsMasterString_astro", hidden=True, options=[SimpleNamespace(item_value="X")])]


def _settings(flag):
    return patch.object(rs, "get_settings", return_value=SimpleNamespace(cpq_required_set_master_string_present_enabled=flag))


def test_flag_off_assumes_nothing():
    with _settings(False):
        assert rs._assumed_master_strings(ATTRS, {}, {}) == {}


def test_only_hidden_option_less_master_strings_the_quote_does_not_fill_are_assumed():
    with _settings(True):
        got = rs._assumed_master_strings(ATTRS, {"baseModel": "X"}, {})
    assert set(got) == {1, 1001}                      # the constraint master string, by entity and source id
    with _settings(True):
        assert rs._assumed_master_strings(ATTRS, {MASTER: "A|B"}, {}) == {}      # filled: the real value wins


def test_pdkey_region_and_options_bearing_attributes_are_never_assumed():
    with _settings(True):
        got = rs._assumed_master_strings(ATTRS, {}, {})
    assert 4 not in got and 5 not in got and 6 not in got


def test_a_rule_with_a_not_blank_master_string_input_fires_only_with_the_flag():
    # baseModel <> '' AND master string <> '' : operators "3" with an empty value, as in the Encryption Type rule
    rule = SimpleNamespace(mode="DISALLOW", blank=True, condition_script=None, guard_attr="", target_attr_id=3,
                           conditions=[(2, "", "3"), (1, "", "3")])
    engine = SimpleNamespace(load_recommendation_and_constraint_rules=lambda *a, **k: ([], [rule]),
                             load_validation_rules=lambda *a, **k: [])
    for flag, expected in ((False, set()), (True, {ENC})):
        with _settings(flag):
            assert rs.rule_required_vns(engine, ATTRS, {"baseModel": "M37"}, {}, 1267, "p") == expected
