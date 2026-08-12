"""Regression coverage: unusual decline phrasing must be recognized as
declining a proposed/pending change, not tried as a literal (failing) new
value (docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md, row
15-16).

`_DECLINE_CHANGE_RE`/`_CHANGE_VALUE_DECLINE_RE` only recognize a fixed
phrase list ("don't want to change", "no change", "never mind", "leave
it", "keep it", "cancel that"). Real declines vary just as much as the
topic-switch redirects this session's other fix already handles — "nah,
forget it", "meh, skip that", "on second thought don't bother" all mean
the same thing but match none of those phrases.

A real regression was caught and fixed while building this: without a
cheap pre-filter gating the LLM fallback, `_is_decline_reply` made an LLM
call on essentially every cascade turn in the whole system (any ordinary
value change like "change solution type to CloudRC" doesn't match the
strict regex either, so it fell through to the same branch). `_LOOSE_
DECLINE_HINT_RE` closes that — several tests below exist specifically to
prove ordinary value changes never reach the LLM at all.
"""
from __future__ import annotations

from unittest.mock import patch

import aryx.api.ask_api as api
from aryx.api.ask_api import (
    AskRequest,
    _is_decline_reply,
    _llm_detect_change_decline,
    _run_cpq_turn,
)
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attr(eid, vn, label, *, options=None, required=False, select_type="single") -> ConfigAttr:
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=label, required=required,
        default_value="", options=options or [], select_type=select_type,
    )


def _rules_setup(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])


def test_llm_detects_an_unusual_decline_phrasing():
    fake_reply = '{"declines_change": true}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _llm_detect_change_decline(
            "nah, forget it", "Hardware Version", "APX NEXT (4G LTE+5G)", workspace_id=1,
        )
    assert result is True


def test_llm_detects_another_unusual_decline_phrasing():
    fake_reply = '{"declines_change": true}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _llm_detect_change_decline(
            "on second thought don't bother", "Solution Type", "RadioCentral", workspace_id=1,
        )
    assert result is True


def test_llm_returns_false_for_a_genuine_value_attempt():
    fake_reply = '{"declines_change": false}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _llm_detect_change_decline(
            "actually let's go with CloudRC", "Solution Type", "RadioCentral", workspace_id=1,
        )
    assert result is False


def test_llm_fails_safe_to_false_on_call_failure():
    with patch("aryx.api.ask_api.llm_runtime.chat", side_effect=RuntimeError("boom")):
        result = _llm_detect_change_decline(
            "nah, forget it", "Hardware Version", "APX NEXT", workspace_id=1,
        )
    assert result is False


def test_llm_fails_safe_to_false_on_malformed_response():
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=("not json", 10, 5)):
        result = _llm_detect_change_decline(
            "nah, forget it", "Hardware Version", "APX NEXT", workspace_id=1,
        )
    assert result is False


def test_combined_check_short_circuits_on_deterministic_hit_without_llm():
    with patch("aryx.api.ask_api.llm_runtime.chat") as mock_chat:
        result = _is_decline_reply(
            "no change", "Hardware Version", "APX NEXT", workspace_id=1,
            deterministic_hit=True,
        )
    assert result is True
    mock_chat.assert_not_called()


def test_combined_check_falls_back_to_llm_for_unusual_phrasing():
    fake_reply = '{"declines_change": true}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _is_decline_reply(
            "nah, forget it", "Hardware Version", "APX NEXT", workspace_id=1,
            deterministic_hit=False,
        )
    assert result is True


def test_combined_check_never_calls_llm_for_an_ordinary_value_change():
    """The regression this fix's own implementation caught: an ordinary
    new-value reply must never reach the LLM fallback at all, since it
    contains none of the loose decline-hint words."""
    with patch("aryx.api.ask_api.llm_runtime.chat") as mock_chat:
        result = _is_decline_reply(
            "CloudRC", "Solution Type", "RadioCentral", workspace_id=1,
            deterministic_hit=False,
        )
    assert result is False
    mock_chat.assert_not_called()


def test_combined_check_never_calls_llm_for_a_real_change_request_sentence():
    """A full, ordinary change-request sentence containing a real
    catalog value must also never reach the LLM fallback."""
    with patch("aryx.api.ask_api.llm_runtime.chat") as mock_chat:
        result = _is_decline_reply(
            "change solution type to CloudRC", "Solution Type", "RadioCentral",
            workspace_id=1, deterministic_hit=False,
        )
    assert result is False
    mock_chat.assert_not_called()


def test_combined_check_stays_false_when_llm_says_not_a_decline():
    fake_reply = '{"declines_change": false}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _is_decline_reply(
            "actually I don't want the old one, use CloudRC instead",
            "Solution Type", "RadioCentral", workspace_id=1, deterministic_hit=False,
        )
    assert result is False


def test_pending_change_no_value_unusual_decline_leaves_value_unchanged(monkeypatch):
    """End-to-end: "nah, forget it" after a "which value?" ask must
    cancel the change via the LLM fallback -- the exact live-bug shape
    _DECLINE_CHANGE_RE/_CHANGE_VALUE_DECLINE_RE never covered."""
    _rules_setup(monkeypatch)
    hw = _attr(1, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H45"))
    attrs = [hw]
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                         filled={"hWVersion_astro": "H1"},
                         display_filled={"hWVersion_astro": "H1"},
                         pending_change_no_value_vn="hWVersion_astro",
                         country="United States", status="configuring", turn=3)
    req = AskRequest(question="nah, forget it", workspace_id=1, session_data=session.to_dict())
    fake_reply = '{"declines_change": true}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        resp = _run_cpq_turn(req, object())
    assert resp
    assert resp["session_data"]["filled"].get("hWVersion_astro") == "H1", (
        "decline must never overwrite the current value"
    )
    assert resp["session_data"]["pending_change_no_value_vn"] == ""
    assert resp["tools_called"] == ["cpq_change_declined()"]
