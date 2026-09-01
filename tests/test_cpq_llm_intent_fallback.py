"""Regression coverage: LLM fallback for remove/change intent when regex
detectors find nothing.

Scoped per Andie session 2026-07-22 — regex stays the fast path;
`_llm_classify_change_intent` only fires downstream of it, reusing the
existing menial-tier model (no new model config), and never trusts an
attribute name the model invents.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.api.ask_api import _llm_classify_change_intent
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _mount_attr() -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi",
        options=_menu("Shirt Magnetic Mount", "Jacket Magnetic Mount"),
    )


def _service_attr() -> ConfigAttr:
    return ConfigAttr(
        entity_id=2, variable_name="serviceType_viSoln", display_label="Service Type",
        required=True, default_value="", select_type="single",
        options=_menu("1 YEAR STANDARD WARRANTY ONLY", "2 YEAR EXTENDED WARRANTY"),
    )


def _session(**overrides) -> CpqSession:
    sess = CpqSession(product_name="videoSolutions_BOM")
    sess.filled = overrides.get("filled", {"serviceType_viSoln": "1 YEAR STANDARD WARRANTY ONLY"})
    sess.filled_multi = overrides.get(
        "filled_multi",
        {"mountingTypeArray_viSoln": ["Shirt Magnetic Mount", "Jacket Magnetic Mount"]},
    )
    return sess


def test_llm_fallback_detects_removal_phrase_regex_would_miss():
    attrs = [_mount_attr(), _service_attr()]
    session = _session()
    fake_reply = (
        '{"intent": "remove", "variable_name": "mountingTypeArray_viSoln", '
        '"value": "Jacket Magnetic Mount"}'
    )
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result, prompt_tokens, completion_tokens = _llm_classify_change_intent(
            "can you get that jacket one off the list", attrs, session, workspace_id=1)
    assert result == {
        "intent": "remove", "variable_name": "mountingTypeArray_viSoln",
        "value": "Jacket Magnetic Mount",
    }
    assert (prompt_tokens, completion_tokens) == (10, 5)


def test_llm_fallback_detects_change_phrase():
    attrs = [_mount_attr(), _service_attr()]
    session = _session()
    fake_reply = (
        '{"intent": "change", "variable_name": "serviceType_viSoln", '
        '"value": "2 YEAR EXTENDED WARRANTY"}'
    )
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result, prompt_tokens, completion_tokens = _llm_classify_change_intent(
            "bump up the warranty coverage please", attrs, session, workspace_id=1)
    assert result == {
        "intent": "change", "variable_name": "serviceType_viSoln",
        "value": "2 YEAR EXTENDED WARRANTY",
    }
    assert (prompt_tokens, completion_tokens) == (10, 5)


def test_llm_fallback_rejects_invented_attribute_name():
    attrs = [_mount_attr(), _service_attr()]
    session = _session()
    fake_reply = (
        '{"intent": "change", "variable_name": "totallyMadeUp_viSoln", "value": "X"}'
    )
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result, _prompt_tokens, _completion_tokens = _llm_classify_change_intent(
            "do the thing", attrs, session, workspace_id=1)
    assert result is None


def test_llm_fallback_none_intent_returns_none():
    attrs = [_mount_attr(), _service_attr()]
    session = _session()
    fake_reply = '{"intent": "none", "variable_name": "", "value": ""}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result, _prompt_tokens, _completion_tokens = _llm_classify_change_intent(
            "what a nice day", attrs, session, workspace_id=1)
    assert result is None


def test_llm_fallback_handles_malformed_json_gracefully():
    attrs = [_mount_attr(), _service_attr()]
    session = _session()
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=("not json at all", 10, 5)):
        result, _prompt_tokens, _completion_tokens = _llm_classify_change_intent(
            "garbage in", attrs, session, workspace_id=1)
    assert result is None


def test_llm_fallback_none_when_no_candidate_attrs_filled():
    attrs = [_mount_attr(), _service_attr()]
    session = _session(filled={}, filled_multi={})
    result, _prompt_tokens, _completion_tokens = _llm_classify_change_intent(
        "remove something", attrs, session, workspace_id=1)
    assert result is None
