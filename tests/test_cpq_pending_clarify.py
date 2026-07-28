"""Gateway clarify memory — pending_clarify_* must resolve bare replies.

Live gap (2026-07-28):
  User: "change hardware"
  Aryx: "Which hardware attribute — Hardware Version, or System Key?"
  User: "Hardware Version"
  Aryx: "I didn't quite catch that" + config table dump

Root cause: gateway action=clarify returned a question but saved no pending
state, so the bare noun had no memory of the clarify and fell through every
detector to the review nudge.

These tests cover the offline contract (no live LLM required for the
deterministic match paths).
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.api.ask_api import (
    AskRequest,
    _clear_pending_clarify,
    _ground_clarify_candidates,
    _grounded_clarify_prompt,
    _handle_pending_clarify_turn,
    _match_pending_clarify_reply,
    _set_pending_clarify_and_answer,
)
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [
        MenuOption(item_value=v, display_name=v, order=i)
        for i, v in enumerate(values, start=1)
    ]


def _hw_version() -> ConfigAttr:
    return ConfigAttr(
        entity_id=1,
        variable_name="hWVersion_astro",
        display_label="Hardware Version",
        required=True,
        default_value="",
        select_type="single",
        options=_menu("APX NEXT (4G LTE Only)", "APX NEXT (4G LTE+5G)"),
        catalog_prefix="aSTRO25",
    )


def _system_key() -> ConfigAttr:
    return ConfigAttr(
        entity_id=2,
        variable_name="systemKey_astro",
        display_label="System Key",
        required=False,
        default_value="",
        select_type="single",
        options=_menu("Key A", "Key B"),
        catalog_prefix="aSTRO25",
    )


def _service() -> ConfigAttr:
    return ConfigAttr(
        entity_id=3,
        variable_name="serviceType_astro",
        display_label="Primary Service Type",
        required=False,
        default_value="",
        select_type="single",
        options=_menu("Advantage", "Essential"),
        catalog_prefix="aSTRO25",
    )


def _session() -> CpqSession:
    s = CpqSession(product_name="aSTRO25_bom", status="awaiting_approval")
    s.filled = {
        "hWVersion_astro": "APX NEXT (4G LTE Only)",
        "systemKey_astro": "Key A",
        "serviceType_astro": "Advantage",
    }
    s.display_filled = {
        "hWVersion_astro": "APX NEXT (4G LTE Only)",
        "systemKey_astro": "Key A",
        "serviceType_astro": "Advantage",
    }
    s.filled_source = {k: "user" for k in s.filled}
    return s


def test_ground_candidates_from_utterance_and_cq_labels():
    attrs = [_hw_version(), _system_key(), _service()]
    session = _session()
    cq = "Which hardware attribute — Hardware Version, or System Key?"
    cands = _ground_clarify_candidates("change hardware", attrs, session, cq)
    vns = {a.variable_name for a in cands}
    assert "hWVersion_astro" in vns
    assert "systemKey_astro" in vns
    # Unrelated filled attr must not be forced in without signal
    assert "serviceType_astro" not in vns


def test_grounded_prompt_uses_catalog_labels_only():
    attrs = [_hw_version(), _system_key()]
    prompt = _grounded_clarify_prompt(attrs, attrs)
    assert "Hardware Version" in prompt
    assert "System Key" in prompt
    assert "hWVersion_astro" in prompt
    assert "1." in prompt and "2." in prompt


def test_match_reply_by_label():
    cands = [_hw_version(), _system_key()]
    session = _session()
    assert _match_pending_clarify_reply(
        "Hardware Version", cands, session, workspace_id=1,
    ) == "hWVersion_astro"


def test_match_reply_by_index():
    cands = [_hw_version(), _system_key()]
    session = _session()
    assert _match_pending_clarify_reply("1", cands, session, 1) == "hWVersion_astro"
    assert _match_pending_clarify_reply("2", cands, session, 1) == "systemKey_astro"


def test_match_reply_by_variable_name():
    cands = [_hw_version(), _system_key()]
    session = _session()
    assert _match_pending_clarify_reply(
        "hWVersion_astro", cands, session, 1,
    ) == "hWVersion_astro"


def test_unrelated_reply_does_not_misbind():
    cands = [_hw_version(), _system_key()]
    session = _session()
    with patch(
        "aryx.api.ask_api._llm_resolve_label_collision",
        return_value=None,
    ):
        assert _match_pending_clarify_reply(
            "what's the weather in Houston", cands, session, 1,
        ) is None


def test_set_pending_clarify_stores_candidates_and_tokens():
    attrs = [_hw_version(), _system_key(), _service()]
    session = _session()
    req = AskRequest(
        question="change hardware",
        workspace_id=1,
        history=[],
        session_data=session.to_dict(),
    )
    with patch("aryx.api.ask_api._persist_cpq_history"):
        resp = _set_pending_clarify_and_answer(
            req, session, attrs,
            original_question="change hardware",
            clarifying_question=(
                "Which hardware attribute — Hardware Version, or System Key?"
            ),
            con_rules=[],
            bml_eval=None,
            prompt_tokens=42,
            completion_tokens=17,
        )
    assert session.pending_clarify_vns
    assert "hWVersion_astro" in session.pending_clarify_vns
    assert session.pending_clarify_question == "change hardware"
    assert "Hardware Version" in resp["answer"]
    assert "System Key" in resp["answer"]
    # Real gateway usage must not be zeroed out
    assert resp["usage"]["prompt_tokens"] == 42
    assert resp["usage"]["completion_tokens"] == 17
    assert "cpq_intent_gateway_clarify()" in resp["tools_called"]


def test_pending_clarify_turn_resolves_to_no_value_prompt():
    attrs = [_hw_version(), _system_key()]
    session = _session()
    session.pending_clarify_vns = ["hWVersion_astro", "systemKey_astro"]
    session.pending_clarify_question = "change hardware"
    session.pending_clarify_prompt = _grounded_clarify_prompt(attrs, attrs)
    req = AskRequest(
        question="Hardware Version",
        workspace_id=1,
        history=[],
        session_data=session.to_dict(),
    )
    with patch("aryx.api.ask_api._persist_cpq_history"):
        resp = _handle_pending_clarify_turn(
            req, session, attrs,
            hiding_rules=[], rec_rules=[], con_rules=[], bml_eval=None,
        )
    assert resp is not None
    assert "Hardware Version" in resp["answer"] or "hWVersion" in str(resp.get("tools_called"))
    # After resolution, clarify pending must be cleared and no-value pending set
    assert session.pending_clarify_vns == []
    assert session.pending_change_no_value_vn == "hWVersion_astro"
    assert "cpq_pending_clarify_resolved" in resp["tools_called"][0]


def test_pending_clarify_miss_reprompts_without_binding():
    attrs = [_hw_version(), _system_key()]
    session = _session()
    session.pending_clarify_vns = ["hWVersion_astro", "systemKey_astro"]
    session.pending_clarify_question = "change hardware"
    session.pending_clarify_prompt = _grounded_clarify_prompt(attrs, attrs)
    session.pending_clarify_misses = 0
    req = AskRequest(
        question="tell me a joke",
        workspace_id=1,
        history=[],
        session_data=session.to_dict(),
    )
    with patch("aryx.api.ask_api._persist_cpq_history"), patch(
        "aryx.api.ask_api._llm_resolve_label_collision", return_value=None,
    ):
        resp = _handle_pending_clarify_turn(
            req, session, attrs,
            hiding_rules=[], rec_rules=[], con_rules=[], bml_eval=None,
        )
    assert resp is not None
    assert session.pending_clarify_vns  # still pending — not cleared
    assert session.pending_clarify_misses == 1
    assert session.pending_change_no_value_vn == ""
    assert "cpq_pending_clarify_reprompt()" in resp["tools_called"]


def test_clear_pending_clarify():
    session = _session()
    session.pending_clarify_vns = ["a"]
    session.pending_clarify_question = "q"
    session.pending_clarify_prompt = "p"
    session.pending_clarify_misses = 2
    _clear_pending_clarify(session)
    assert session.pending_clarify_vns == []
    assert session.pending_clarify_question == ""
    assert session.pending_clarify_misses == 0


def test_session_roundtrip_preserves_pending_clarify():
    s = _session()
    s.pending_clarify_vns = ["hWVersion_astro", "systemKey_astro"]
    s.pending_clarify_question = "change hardware"
    s.pending_clarify_prompt = "pick one"
    s.pending_clarify_asked_turn = 4
    s.pending_clarify_misses = 1
    restored = CpqSession.from_dict(s.to_dict())
    assert restored.pending_clarify_vns == s.pending_clarify_vns
    assert restored.pending_clarify_question == "change hardware"
    assert restored.pending_clarify_asked_turn == 4
    assert restored.pending_clarify_misses == 1
