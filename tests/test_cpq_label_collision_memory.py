"""Regression coverage: options-query label-collision prompt has memory
(session.pending_label_collision_vns/_question), with a gated LLM
fallback for looser phrasing.

Live-verified gap, 2026-07-23: "what are the mounting types available?"
fires detect_label_collision's "which one did you mean?" prompt inside
_handle_cpq_qa, but the reply — even the EXACT variable_name shown —
fell through to a generic nudge, since nothing was stored. Same class of
bug already fixed for the change-request collision
(pending_change_collision_vns, commit 2dd5d40) — this is the sibling fix
for the options-query collision, never applied when that one shipped.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.api.ask_api import _llm_resolve_label_collision
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _single_mount() -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="mountType_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="single",
        options=_menu("Swivel Clip", "Adjustable Lanyard"),
    )


def _multi_mount() -> ConfigAttr:
    return ConfigAttr(
        entity_id=2, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi",
        options=_menu("Shirt Magnetic Mount", "Jacket Magnetic Mount"),
    )


def _session() -> CpqSession:
    sess = CpqSession(product_name="videoSolutions_BOM")
    sess.display_filled = {"mountType_viSoln": "Swivel Clip and Adjustable Lanyard"}
    sess.filled_multi = {"mountingTypeArray_viSoln": ["Jacket Magnetic Mount"]}
    return sess


def test_llm_resolver_uses_current_value_to_disambiguate():
    """Live-verified bug: an earlier version of the prompt omitted each
    candidate's current value entirely — a reply naming the CURRENT value
    ("the one that currently has jacket magnetic mount") had no way to
    resolve correctly, since the model was never told what either
    candidate's current value even was. Asserts the prompt now includes
    it and the model's (correct) answer is honored."""
    attrs = [_single_mount(), _multi_mount()]
    session = _session()
    fake_reply = '{"variable_name": "mountingTypeArray_viSoln"}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)) as mock_chat:
        result = _llm_resolve_label_collision(
            "the one that currently has jacket magnetic mount", attrs, session, workspace_id=1)
    assert result == "mountingTypeArray_viSoln"
    prompt_user_msg = mock_chat.call_args[0][2]
    assert "Jacket Magnetic Mount" in prompt_user_msg, (
        "the candidate's current value must be in the prompt for this phrasing to ever resolve"
    )
    assert "Swivel Clip and Adjustable Lanyard" in prompt_user_msg


def test_llm_resolver_rejects_an_invented_variable_name():
    attrs = [_single_mount(), _multi_mount()]
    session = _session()
    fake_reply = '{"variable_name": "someAttrNotInTheList_astro"}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _llm_resolve_label_collision("the mount thing", attrs, session, workspace_id=1)
    assert result is None


def test_llm_resolver_returns_none_on_call_failure():
    attrs = [_single_mount(), _multi_mount()]
    session = _session()
    with patch("aryx.api.ask_api.llm_runtime.chat", side_effect=RuntimeError("boom")):
        result = _llm_resolve_label_collision("the mount thing", attrs, session, workspace_id=1)
    assert result is None


def test_llm_resolver_returns_none_when_model_says_none():
    attrs = [_single_mount(), _multi_mount()]
    session = _session()
    fake_reply = '{"variable_name": ""}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _llm_resolve_label_collision("mounting stuff", attrs, session, workspace_id=1)
    assert result is None
