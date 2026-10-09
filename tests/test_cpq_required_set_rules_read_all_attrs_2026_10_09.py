"""Fixes B and C (flag `cpq_required_set_rules_read_all_attrs_enabled`): a blank-disallow rule's INPUTS are read from the turn's
full attribute list, and an unfilled `_bm_model_variable_name` reads as the resolved model node (ws 1267, APX 900: the
Encryption Type rule reads the constraint master string, Feature Type and the model variable, none of them in the 25 visible
attributes the required set was given)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.cpq.payload_building import required_set as rs
from aryx.cpq.state import ConfigAttr

MASTER, ENC, MODEL = "hiddenConstraintMasterString_astro", "secureEncryptionType_astro", "_bm_model_variable_name"


def _attr(eid, vn, hidden=False):
    return ConfigAttr(entity_id=eid, variable_name=vn, display_label=vn, required=False, default_value="",
                      select_type="single", hidden=hidden, options=[], source_id=eid + 1000)


VISIBLE = [_attr(2, "baseModel"), _attr(3, ENC)]
FULL = [*VISIBLE, _attr(1, MASTER, hidden=True), _attr(7, MODEL, hidden=True)]
RULE = SimpleNamespace(mode="DISALLOW", blank=True, condition_script=None, guard_attr="", target_attr_id=3,
                       conditions=[(2, "", "3"), (1, "", "3"), (7, "aPX900", "4")])        # model = aPX900
ENGINE = SimpleNamespace(load_recommendation_and_constraint_rules=lambda *a, **k: ([], [RULE]),
                         load_validation_rules=lambda *a, **k: [])


def _run(input_attrs, node="aPX900", filled=None, stats=None):
    settings = SimpleNamespace(cpq_required_set_master_string_present_enabled=True,
                               cpq_required_set_guards_assumed_open=False, cpq_required_set_rule_guards_assumed_open=True)
    with patch.object(rs, "get_settings", return_value=settings), \
            patch("aryx.cpq.layout_and_join_data.layout_variant_context.current_model_node", return_value=node):
        return rs.rule_required_vns(ENGINE, VISIBLE, {"baseModel": "M37", **(filled or {})}, {}, 1267, "p", None, stats,
                                    input_attrs)


def test_inputs_outside_the_visible_list_never_fire_the_rule_today():
    stats: dict = {}
    assert _run(None, stats=stats) == set()
    states = {c[0]: c[3] for c in stats["unfired_blank_disallow"][0]["conds"]}
    assert states[f"id:1"] == "unmapped" and states["id:7"] == "unmapped"


def test_reading_the_full_list_fires_it_and_the_target_stays_the_visible_attribute():
    stats: dict = {}
    assert _run(FULL, stats=stats) == {ENC}
    assert stats["blank_disallow_condition_fired"] == 1 and stats["rule_inputs_from_all_attrs"] is True


def test_the_model_variable_reads_the_resolved_node():
    assert _run(FULL, node="aPX900") == {ENC}
    assert _run(FULL, node="aPX8000") == set()               # another model: the rule's model condition is false
    assert _run(FULL, node="") == set()                      # no node resolved: unknown, nothing required


def test_a_quote_value_for_the_model_variable_wins_over_the_node():
    assert _run(FULL, node="aPX8000", filled={MODEL: "aPX900"}) == {ENC}


def test_a_target_missing_from_the_visible_list_is_not_required():
    rule = SimpleNamespace(**{**RULE.__dict__, "target_attr_id": 99})
    engine = SimpleNamespace(load_recommendation_and_constraint_rules=lambda *a, **k: ([], [rule]),
                             load_validation_rules=lambda *a, **k: [])
    settings = SimpleNamespace(cpq_required_set_master_string_present_enabled=True,
                               cpq_required_set_guards_assumed_open=False, cpq_required_set_rule_guards_assumed_open=True)
    with patch.object(rs, "get_settings", return_value=settings):
        assert rs.rule_required_vns(engine, VISIBLE, {"baseModel": "M37"}, {}, 1267, "p", None, None, FULL) == set()


def test_the_loop_stashes_the_full_list_and_setup_reads_it_only_with_the_flag():
    from aryx.cpq.auto_fill import auto_fill_setup as setup
    seen: dict = {}

    def fake_derive(*args, **kwargs):
        seen["input"] = kwargs.get("rule_input_attrs")
        return frozenset()

    for flag, expected in ((False, None), (True, FULL)):
        cache = {("_all_attrs", 1267, "p"): FULL}
        settings = SimpleNamespace(cpq_required_set_asks_enabled=True, cpq_required_set_rule_guards_assumed_open=True,
                                   cpq_required_set_guards_assumed_open=False,
                                   cpq_required_set_rules_read_all_attrs_enabled=flag)
        with patch.object(setup, "get_settings", return_value=settings), \
                patch.object(setup, "_rule_hidden_vns", return_value=set()), \
                patch("aryx.cpq.payload_building.required_set.derive_required_vns", side_effect=fake_derive):
            setup._required_ask_vns(SimpleNamespace(), VISIBLE, {}, {}, {}, None, 1267, "p", "hint", cache)
        assert seen["input"] is expected
