"""Tests for the JSON/Beautify/Share button readiness gate (_attach_share_flags).

Unit-level: monkeypatches load_product_config so these don't need graph
fixtures — the gate's own threshold/status logic is what's under test, not
attribute loading (already covered by test_cpq_e2e.py).
"""
from __future__ import annotations

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _attach_share_flags
from aryx.cpq.state import ConfigAttr, ConstraintRule, CpqSession, MenuOption


def _session_data(filled, display_filled, status="configuring",
                   filled_multi=None, product_name="APX NEXT XE") -> dict:
    return CpqSession(
        product_name=product_name, filled=filled, display_filled=display_filled,
        filled_multi=filled_multi or {}, status=status,
    ).to_dict()


def _req() -> AskRequest:
    return AskRequest(question="anything", workspace_id=1, session_data={})


def _patch_engine(monkeypatch):
    monkeypatch.setattr(
        api._cpq_engine, "load_product_config",
        lambda reader, workspace_id, product_name: ([], product_name),
    )
    # docs/APX_Next_RootCause_And_Fix_Report — Raven review on PR #142:
    # _attach_share_flags now loads hiding/rec/con rules (a plain DB read,
    # no script evaluation) to pass to build_payload's `rules` param for
    # dependency-aware ordering. Mocked here the same way
    # load_product_config already is — these tests exercise the
    # threshold/status gate, not rule loading, and must not need a real DB.
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_recommendation_and_constraint_rules",
        lambda *a, **k: ([], []),
    )


def test_below_threshold_no_flags(monkeypatch):
    _patch_engine(monkeypatch)
    result = {"answer": "...", "session_data": _session_data(
        filled={"carrier": "Verizon", "billing": "Monthly"},
        display_filled={"carrier": "Verizon", "billing": "Monthly"})}
    _attach_share_flags(result, _req(), reader=None)
    assert "json_button_flag" not in result
    assert "beautify_button_flag" not in result
    assert "api_share_button_flag" not in result


def test_at_threshold_json_and_beautify_present_but_share_withheld(monkeypatch):
    _patch_engine(monkeypatch)
    filled = {"carrier": "Verizon", "billing": "Monthly", "activation": "Immediate"}
    result = {"answer": "...", "session_data": _session_data(
        filled=filled, display_filled=filled)}
    _attach_share_flags(result, _req(), reader=None)
    assert result["json_button_flag"] is True
    # Compare against build_payload()'s real, current output rather than a
    # hardcoded literal — its return shape is independently evolving on
    # another branch (flat {var: value} vs nested {"configAttributes": {...}}),
    # so this assertion must track whatever the engine actually produces,
    # not pin to one shape and rot the moment that branch merges.
    assert result["json_response"] == api._cpq_engine.build_payload(filled, {}, {})
    assert result["beautify_button_flag"] is True
    assert "Verizon" in result["beautify"]
    assert any(row["value"] == "Verizon" for row in result["beautify_rows"])
    # Still mid-configuration — nothing to share yet, even though JSON/Beautify are ready.
    assert result["api_share_button_flag"] is False
    assert result["api_share"] == {}


def test_multi_select_answers_count_toward_threshold(monkeypatch):
    _patch_engine(monkeypatch)
    result = {"answer": "...", "session_data": _session_data(
        filled={"carrier": "Verizon"}, display_filled={"carrier": "Verizon"},
        filled_multi={"addons": ["gps"], "features": ["voice"]})}
    _attach_share_flags(result, _req(), reader=None)
    assert result["json_button_flag"] is True


def test_awaiting_approval_bypasses_threshold_and_enables_share(monkeypatch):
    _patch_engine(monkeypatch)
    filled = {"carrier": "Verizon"}
    result = {"answer": "...", "session_data": _session_data(
        filled=filled, display_filled=filled, status="awaiting_approval")}
    _attach_share_flags(result, _req(), reader=None)
    assert result["json_button_flag"] is True
    assert result["api_share_button_flag"] is True
    # See note above — asserted against the live build_payload() output, not
    # a hardcoded shape, so this survives the in-flight payload-shape change.
    assert result["api_share"] == api._cpq_engine.build_payload(filled, {}, {})


def test_no_session_data_is_noop():
    result = {"answer": "..."}
    _attach_share_flags(result, _req(), reader=None)
    assert "json_button_flag" not in result


def test_no_product_name_yet_is_noop(monkeypatch):
    _patch_engine(monkeypatch)
    result = {"answer": "...", "session_data": _session_data(
        filled={"carrier": "Verizon", "billing": "Monthly", "activation": "Immediate"},
        display_filled={"carrier": "Verizon", "billing": "Monthly", "activation": "Immediate"},
        product_name="")}
    _attach_share_flags(result, _req(), reader=None)
    assert "json_button_flag" not in result


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=f"Display {v}", order=i)
            for i, v in enumerate(values, start=1)]


def test_json_response_is_dependency_ordered_not_just_order_number(monkeypatch):
    """Raven review on PR #142 (docs/APX_Next_RootCause_And_Fix_Report):
    the web UI's JSON/share-button preview (this function's own
    json_response) is customer-visible and must not exhibit the exact
    order_number-only sequencing bug the rest of the PR fixed elsewhere —
    e.g. an attribute placed ahead of the other attribute that gates it.
    Made-up attribute/rule names, not real APX Next data."""
    attrs = [
        ConfigAttr(entity_id=10, source_id=10, variable_name="gate",
                   display_label="Gate Attr", required=False, default_value="",
                   options=_menu("A", "B"), order=128),
        ConfigAttr(entity_id=20, source_id=20, variable_name="gated",
                   display_label="Gated Attr", required=False, default_value="",
                   options=_menu("X", "Y"), order=26),
    ]
    monkeypatch.setattr(
        api._cpq_engine, "load_product_config",
        lambda reader, workspace_id, product_name: (attrs, product_name),
    )
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    con_rules = [
        ConstraintRule(rule_name="Restrict gated based on gate",
                        condition_attr_id=10, condition_value="A",
                        target_attr_id=20, allowed_values=["X"]),
    ]
    monkeypatch.setattr(
        api._cpq_engine, "load_recommendation_and_constraint_rules",
        lambda *a, **k: ([], con_rules),
    )
    filled = {"gate": "A", "gated": "X", "extra": "1"}
    result = {"answer": "...", "session_data": _session_data(
        filled=filled, display_filled=filled)}
    _attach_share_flags(result, _req(), reader=None)
    keys = list(result["json_response"]["configData"].keys())
    assert keys.index("gate") < keys.index("gated"), (
        "the share-preview payload must respect the rule-proven dependency, "
        "not order_number alone (gate=128, gated=26 -- inverted)"
    )
