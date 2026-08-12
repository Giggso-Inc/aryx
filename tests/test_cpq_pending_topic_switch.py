"""Regression coverage: a natural-language redirect away from an actively
pending single-select question must be recognized as a topic switch, not
locked in as a failed answer attempt (docs/CPQ_PENDING_TOPIC_SWITCH_PLAN_
2026_08_11.md).

Live-verified gap, 2026-08-11: Hardware Version was pending; the customer
tried three different natural-language ways to redirect to Carrier
Selection instead ("I wanted to check the carrier selection value",
"I don't want hardware version but carrier selection", "I don't want to
select the hardware version but i wanted to check with carrier
selection"). None contain the deterministic `_CHANGE_VERB_RE`/`_ARROW_RE`
phrasing `_pending_reply_looks_like_new_request` requires, so all three
were misread as invalid answers to Hardware Version and re-asked forever.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.api.ask_api import (
    _llm_detect_pending_topic_switch,
    _pending_reply_is_topic_switch,
)
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _hardware_version() -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="hardwareVersion_astro", display_label="Hardware Version",
        required=True, default_value="", select_type="single",
        options=_menu("APX NEXT (4G LTE+5G)", "APX NEXT (4G LTE Only)"),
    )


def _carrier_selection() -> ConfigAttr:
    return ConfigAttr(
        entity_id=2, variable_name="carrierSelection_astro", display_label="Carrier Selection",
        required=False, default_value="", select_type="single",
        options=_menu("AT&T", "Verizon"),
    )


def test_llm_detects_a_named_redirect_to_a_different_attribute():
    pending = _hardware_version()
    other = [_carrier_selection()]
    fake_reply = '{"switch_to": "carrierSelection_astro"}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _llm_detect_pending_topic_switch(
            "I wanted to check the carrier selection value", pending, other, workspace_id=1,
        )
    assert result == "carrierSelection_astro"


def test_llm_rejects_an_invented_variable_name():
    pending = _hardware_version()
    other = [_carrier_selection()]
    fake_reply = '{"switch_to": "someAttrNotInTheList_astro"}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _llm_detect_pending_topic_switch(
            "I don't want hardware version but carrier selection", pending, other, workspace_id=1,
        )
    assert result is None


def test_llm_returns_none_when_model_says_none():
    pending = _hardware_version()
    other = [_carrier_selection()]
    fake_reply = '{"switch_to": "none"}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _llm_detect_pending_topic_switch(
            "APX NEXT (4G LTE+5G)", pending, other, workspace_id=1,
        )
    assert result is None


def test_llm_returns_none_on_call_failure():
    pending = _hardware_version()
    other = [_carrier_selection()]
    with patch("aryx.api.ask_api.llm_runtime.chat", side_effect=RuntimeError("boom")):
        result = _llm_detect_pending_topic_switch(
            "I wanted to check the carrier selection value", pending, other, workspace_id=1,
        )
    assert result is None


def test_combined_check_short_circuits_on_deterministic_match_without_llm():
    """A genuine 'change X to Y' style message must never even reach the
    LLM — the deterministic path already handles it, and the LLM must not
    be trusted to override it either way."""
    pending = _hardware_version()
    carrier = _carrier_selection()
    attrs = [pending, carrier]
    filled = {carrier.variable_name: "Verizon"}
    with patch("aryx.api.ask_api.llm_runtime.chat") as mock_chat:
        result = _pending_reply_is_topic_switch(
            "change carrier selection to AT&T", pending, attrs, filled, {}, workspace_id=1,
        )
    assert result is True
    mock_chat.assert_not_called()


def test_combined_check_falls_back_to_llm_for_natural_language_redirect():
    pending = _hardware_version()
    attrs = [pending, _carrier_selection()]
    fake_reply = '{"switch_to": "carrierSelection_astro"}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _pending_reply_is_topic_switch(
            "I don't want to select the hardware version but i wanted to check with carrier selection",
            pending, attrs, {}, {}, workspace_id=1,
        )
    assert result is True


def test_combined_check_live_2026_08_11_wireless_carrier_phrasing():
    """'wanted to changed' (not 'change'/'changing') doesn't match
    _CHANGE_VERB_RE at all -- confirmed live to leave the pending
    'which value?' mechanism with no signal, forcing the whole message
    into apply_answer against the wrong (pending) attr and producing
    'I couldn't match that to a valid option for Hardware Version.'"""
    pending = _hardware_version()
    carrier = _carrier_selection()
    carrier.display_label = "Wireless Carrier"
    attrs = [pending, carrier]
    fake_reply = '{"switch_to": "carrierSelection_astro"}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _pending_reply_is_topic_switch(
            "First i wanted to changed Wireless Carrier",
            pending, attrs, {}, {}, workspace_id=1,
        )
    assert result is True


def test_combined_check_second_reported_phrasing():
    pending = _hardware_version()
    attrs = [pending, _carrier_selection()]
    fake_reply = '{"switch_to": "carrierSelection_astro"}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _pending_reply_is_topic_switch(
            "I don't want hardware version but carrier selection",
            pending, attrs, {}, {}, workspace_id=1,
        )
    assert result is True


def test_combined_check_stays_false_for_a_genuine_answer_attempt():
    pending = _hardware_version()
    attrs = [pending, _carrier_selection()]
    fake_reply = '{"switch_to": "none"}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _pending_reply_is_topic_switch(
            "APX NEXT (4G LTE+5G)", pending, attrs, {}, {}, workspace_id=1,
        )
    assert result is False


def test_combined_check_returns_false_with_no_pending_attr():
    attrs = [_hardware_version(), _carrier_selection()]
    result = _pending_reply_is_topic_switch(
        "whatever", None, attrs, {}, {}, workspace_id=1,
    )
    assert result is False


def test_combined_check_skips_llm_when_no_other_attrs_exist():
    pending = _hardware_version()
    with patch("aryx.api.ask_api.llm_runtime.chat") as mock_chat:
        result = _pending_reply_is_topic_switch(
            "something unrelated", pending, [pending], {}, {}, workspace_id=1,
        )
    assert result is False
    mock_chat.assert_not_called()


# ── Negative cases: must NOT be misclassified as a switch ──────────────────


def test_change_verb_naming_the_pending_attr_itself_is_not_a_switch():
    """'select hardware version' has a change-verb match (_CHANGE_VERB_RE
    fires on 'select'), but the only real attr it names IS the pending
    one -- `other_attrs` excludes it by construction, so the deterministic
    check's own 'and' clause must fail, and the LLM (asked only about
    OTHER candidates) must also find nothing to switch to."""
    pending = _hardware_version()
    attrs = [pending, _carrier_selection()]
    fake_reply = '{"switch_to": "none"}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _pending_reply_is_topic_switch(
            "let me select hardware version 4G LTE Only",
            pending, attrs, {}, {}, workspace_id=1,
        )
    assert result is False


def test_shared_option_value_across_attrs_is_not_misread_as_a_switch():
    """Docstring-referenced live gap: 'VHF' is a legal option on BOTH the
    pending attr and a sibling attr. A bare reply that's actually
    answering the pending question with a value that HAPPENS to also be
    a legal value elsewhere must stay a plain answer (LLM says 'none'),
    not get redirected to the sibling."""
    pending = _hardware_version()
    sibling = _carrier_selection()
    sibling.options = _menu("VHF", "UHF")
    attrs = [pending, sibling]
    fake_reply = '{"switch_to": "none"}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _pending_reply_is_topic_switch(
            "VHF", pending, attrs, {}, {}, workspace_id=1,
        )
    assert result is False


def test_combined_check_fails_safe_on_llm_error_treating_reply_as_an_answer():
    """If the LLM call itself blows up, the combined check must default
    to False (treat the reply as a plain answer attempt) rather than
    propagating the exception or silently guessing a switch -- a failed
    LLM call must never be more disruptive than no LLM call at all."""
    pending = _hardware_version()
    attrs = [pending, _carrier_selection()]
    with patch("aryx.api.ask_api.llm_runtime.chat", side_effect=RuntimeError("boom")):
        result = _pending_reply_is_topic_switch(
            "I wanted to check the carrier selection value",
            pending, attrs, {}, {}, workspace_id=1,
        )
    assert result is False


def test_combined_check_fails_safe_on_malformed_llm_json():
    """A non-JSON or schema-mismatched reply from the model must resolve
    to 'not a switch', same fail-safe direction as a call failure."""
    pending = _hardware_version()
    attrs = [pending, _carrier_selection()]
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=("not json at all", 10, 5)):
        result = _pending_reply_is_topic_switch(
            "I don't want hardware version but carrier selection",
            pending, attrs, {}, {}, workspace_id=1,
        )
    assert result is False
