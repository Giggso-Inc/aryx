"""Tests for the JSON/Beautify/Share button readiness gate (_attach_share_flags).

Unit-level: monkeypatches load_product_config so these don't need graph
fixtures — the gate's own threshold/status logic is what's under test, not
attribute loading (already covered by test_cpq_e2e.py).
"""
from __future__ import annotations

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _attach_share_flags
from aryx.cpq.state import CpqSession


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
    result = {"answer": "...", "session_data": _session_data(
        filled={"carrier": "Verizon", "billing": "Monthly", "activation": "Immediate"},
        display_filled={"carrier": "Verizon", "billing": "Monthly", "activation": "Immediate"})}
    _attach_share_flags(result, _req(), reader=None)
    assert result["json_button_flag"] is True
    assert result["json_response"] == {
        "carrier": "Verizon", "billing": "Monthly", "activation": "Immediate"}
    assert result["beautify_button_flag"] is True
    assert "Verizon" in result["beautify"]
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
    result = {"answer": "...", "session_data": _session_data(
        filled={"carrier": "Verizon"}, display_filled={"carrier": "Verizon"},
        status="awaiting_approval")}
    _attach_share_flags(result, _req(), reader=None)
    assert result["json_button_flag"] is True
    assert result["api_share_button_flag"] is True
    assert result["api_share"] == {"carrier": "Verizon"}


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
