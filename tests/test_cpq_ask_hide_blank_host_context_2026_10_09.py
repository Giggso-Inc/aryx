"""The ask-set hide check counts host-supplied context as blank (flag `cpq_ask_hide_assumes_blank_host_context_enabled`).

ws 1267: 'Do You Require Radio FCC Trigger?' is required by a country-conditioned blank-disallow rule and hidden by 'Hide ... on
Non FED Customer', which cannot fire without Customer Type (the host supplies it). It was asked first on every product."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.cpq.auto_fill import auto_fill_setup as setup

FCC = "requireForRadioFEDFCCTriggerSS_astro"


def _attr(vn, options=(), select_type="single", eid=0, source_id=None):
    return SimpleNamespace(variable_name=vn, options=list(options), select_type=select_type, entity_id=eid,
                           source_id=source_id)


CUSTOMER_TYPE_ID = 11
ATTRS = [_attr("customerType", eid=1, source_id=CUSTOMER_TYPE_ID), _attr("customerUIN", eid=2),
         _attr("ultimateDestinationCountry", ["US", "CA"], eid=3), _attr(FCC, ["YES", "NO"], eid=4),
         _attr("someQuantity_astro", select_type="integer", eid=5), _attr("someNote_astro", eid=6),
         _attr("someFlag_astro", select_type="boolean", eid=7)]
# 'Hide on Non FED Customer': customerType <> FEDERAL, and a numeric and a boolean attribute are tested as well
DECLARATIVE = SimpleNamespace(script=None, name="Hide on Non FED Customer", condition_attr_id=0,
                              conditions=[(CUSTOMER_TYPE_ID, "FEDERAL", "3"), (5, "0", "3"), (7, "", "3")])
SCRIPTED = SimpleNamespace(script="if (...) {}", name="master string hide")


def _run(flag, filled, base_known):
    calls = []

    def apply(attrs, f, rules, bml, multi, **kw):
        calls.append({"filled": dict(f), "rules": list(rules)})
        return ([], [], {FCC} if rules == [DECLARATIVE] else {"scripted_hidden"})

    engine = SimpleNamespace(load_hiding_rules=lambda *a, **k: [DECLARATIVE, SCRIPTED], apply_hiding_rules=apply)
    base = "baseModel"
    with patch.object(setup, "get_settings", return_value=SimpleNamespace(
            cpq_ask_hide_assumes_blank_host_context_enabled=flag)), \
            patch("aryx.cpq.catalog_profile.resolve_base_model_vn", return_value=base):
        out = setup._rule_hidden_vns(engine, ATTRS, {**filled, **({base: "M37"} if base_known else {})}, {}, 1267, "p",
                                     "APX 8500", {}, None)
    return out, calls


def test_flag_off_and_no_base_model_hides_nothing_and_evaluates_nothing():
    out, calls = _run(False, {"ultimateDestinationCountry": "US"}, base_known=False)
    assert out == set() and calls == []


def test_flag_on_before_the_base_model_runs_declarative_rules_only_with_blank_host_context():
    out, calls = _run(True, {"ultimateDestinationCountry": "US"}, base_known=False)
    assert out == {FCC}
    assert len(calls) == 1 and calls[0]["rules"] == [DECLARATIVE]
    assert calls[0]["filled"]["customerType"] == ""          # free text, tested by the rule (by its source id), not carried


def test_attributes_with_options_or_answers_are_never_blanked():
    _, calls = _run(True, {"ultimateDestinationCountry": "US"}, base_known=False)
    filled = calls[0]["filled"]
    assert filled["ultimateDestinationCountry"] == "US"      # answered: untouched
    assert FCC not in filled                                  # has options, unanswered: stays unknown


def test_only_free_text_attributes_a_declarative_hide_rule_tests_are_blanked():
    _, calls = _run(True, {"ultimateDestinationCountry": "US"}, base_known=False)
    filled = calls[0]["filled"]
    assert "customerUIN" not in filled and "someNote_astro" not in filled      # free text, but no declarative rule tests them
    assert "someQuantity_astro" not in filled and "someFlag_astro" not in filled   # numeric / boolean: never invented


def test_flag_on_after_the_base_model_keeps_the_full_pass_with_the_real_answers():
    out, calls = _run(True, {"ultimateDestinationCountry": "US"}, base_known=True)
    assert out == {FCC, "scripted_hidden"}
    assert calls[0]["rules"] == [DECLARATIVE, SCRIPTED] and "customerType" not in calls[0]["filled"]
    assert calls[1]["rules"] == [DECLARATIVE] and calls[1]["filled"]["customerType"] == ""


def test_a_failing_hide_check_is_logged_as_a_warning_and_hides_nothing():
    engine = SimpleNamespace(load_hiding_rules=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
                             apply_hiding_rules=lambda *a, **k: ([], [], set()))
    with patch.object(setup, "get_settings", return_value=SimpleNamespace(
            cpq_ask_hide_assumes_blank_host_context_enabled=True)), \
            patch("aryx.cpq.catalog_profile.resolve_base_model_vn", return_value="baseModel"), \
            patch.object(setup, "raven_log") as log:
        out = setup._rule_hidden_vns(engine, ATTRS, {"ultimateDestinationCountry": "US"}, {}, 1267, "p", "APX 8500", {}, None)
    assert out == set()
    assert any(c.args[0] == "WARN" and "hide_check_failed" in c.args[2] for c in log.call_args_list)


def test_a_logging_failure_inside_the_error_handler_does_not_escape():
    engine = SimpleNamespace(load_hiding_rules=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
                             apply_hiding_rules=lambda *a, **k: ([], [], set()))
    with patch.object(setup, "get_settings", return_value=SimpleNamespace(
            cpq_ask_hide_assumes_blank_host_context_enabled=True)), \
            patch("aryx.cpq.catalog_profile.resolve_base_model_vn", return_value="baseModel"), \
            patch.object(setup, "raven_log", side_effect=RuntimeError("logging is down")):
        out = setup._rule_hidden_vns(engine, ATTRS, {"ultimateDestinationCountry": "US"}, {}, 1267, "p", "APX 8500", {}, None)
    assert out == set()
