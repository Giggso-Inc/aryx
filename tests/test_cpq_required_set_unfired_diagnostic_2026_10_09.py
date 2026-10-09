"""Diagnostic for blank-disallow rules that did not fire (logging only): ws 1267 APX 900, `attr_count 25`,
`blank_disallow_loaded 19`, `blank_disallow_condition_fired 1`: Encryption Type's rule never fires and the log did not say why."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.cpq.payload_building import required_set as rs
from aryx.cpq.state import ConfigAttr

ENC = "secureEncryptionType_astro"


def _attr(eid, vn, source_id=None):
    return ConfigAttr(entity_id=eid, variable_name=vn, display_label=vn, required=False, default_value="",
                      select_type="single", hidden=False, options=[], source_id=source_id)


def _rule(conditions, name="Restrict blank value for Encryption Type for US or FED customers"):
    return SimpleNamespace(rule_name=name, mode="DISALLOW", blank=True, condition_script=None, guard_attr="",
                           target_attr_id=3, conditions=conditions)


def _run(rules, attrs, filled):
    engine = SimpleNamespace(load_recommendation_and_constraint_rules=lambda *a, **k: ([], rules),
                             load_validation_rules=lambda *a, **k: [])
    stats: dict = {}
    with patch.object(rs, "get_settings", return_value=SimpleNamespace(cpq_required_set_guards_assumed_open=False)):
        found = rs.rule_required_vns(engine, attrs, filled, {}, 1267, "p", None, stats)
    return found, stats


ATTRS = [_attr(1, "ultimateDestinationCountry"), _attr(2, "modelSelectionbaseModel_astro"), _attr(3, ENC)]
FILLED = {"ultimateDestinationCountry": "US", "modelSelectionbaseModel_astro": "H92UCH9PW7AN"}


def test_a_condition_on_an_attribute_outside_the_list_is_reported_as_unmapped():
    # base model not blank, country = US, customerType (id 99, not in the list) = FEDERAL, master string (id 98) not blank
    rule = _rule([(2, "", "3"), (1, "US", "4"), (99, "FEDERAL", "4"), (98, "", "3")])
    found, stats = _run([rule], ATTRS, FILLED)
    assert found == set()                                              # the result is unchanged by the diagnostic
    entry = stats["unfired_blank_disallow"][0]
    assert entry["target"] == ENC and entry["script_condition"] is False
    states = {c[0]: c[3] for c in entry["conds"]}
    assert states["id:99"] == "unmapped" and states["id:98"] == "unmapped"
    assert states["modelSelectionbaseModel_astro"] == "true" and states["ultimateDestinationCountry"] == "true"


def test_a_known_false_condition_is_reported_as_false():
    rule = _rule([(1, "CA", "4")])
    _, stats = _run([rule], ATTRS, FILLED)
    assert stats["unfired_blank_disallow"][0]["conds"] == [["ultimateDestinationCountry", "4", "CA", "false"]]


def test_a_rule_that_fires_is_not_listed_and_the_list_is_capped():
    found, stats = _run([_rule([(1, "US", "4")])], ATTRS, FILLED)
    assert found == {ENC} and stats["unfired_blank_disallow"] == []
    many = [_rule([(99, "X", "4")], name=f"r{i}") for i in range(30)]
    _, stats = _run(many, ATTRS, FILLED)
    assert stats["blank_disallow_loaded"] == 30 and len(stats["unfired_blank_disallow"]) == 20


def test_without_stats_nothing_extra_is_computed():
    engine = SimpleNamespace(load_recommendation_and_constraint_rules=lambda *a, **k: ([], [_rule([(99, "X", "4")])]),
                             load_validation_rules=lambda *a, **k: [])
    with patch.object(rs, "get_settings", return_value=SimpleNamespace(cpq_required_set_guards_assumed_open=False)), \
            patch.object(rs, "_condition_states", side_effect=AssertionError("must not run")):
        assert rs.rule_required_vns(engine, ATTRS, FILLED, {}, 1267, "p") == set()


def test_the_diagnostic_line_carries_the_unfired_rules():
    with patch("aryx.raven_log.would_log", return_value=True), patch("aryx.raven_log.raven_log") as log:
        rs._log_required_set_diagnostic(rule_only=True, stats={"unfired_blank_disallow": [{"rule": "r", "conds": []}]},
                                        found=set(), dropped={}, kept=set(), models=["APX900"], base_model="H92", attr_count=25)
    assert log.call_args.kwargs["context"]["unfired_blank_disallow"] == [{"rule": "r", "conds": []}]
