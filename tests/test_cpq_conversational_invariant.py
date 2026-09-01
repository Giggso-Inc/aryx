"""Conversational invariant: no orphan config questions.

A turn that ends by asking the user about a specific attribute/anchor
MUST leave consumable pending state (pending_variables, pending_clarify,
pending_change_no_value_vn, pending_switch_*, …). This makes the
"clarify amnesia" bug family fail closed in tests and log
``cpq_orphan_question`` in production.
"""
from __future__ import annotations

from aryx.cpq.session_guard import (
    answer_is_config_question,
    assert_conversational_invariant,
    enforce_conversational_invariant,
    has_consumable_pending_state,
    match_clarify_reply_offline,
    numbered_attr_pick_prompt,
)
from aryx.cpq.state import CpqSession


def test_answer_is_config_question_detects_which_attribute():
    q = (
        "Which attribute did you mean? Reply with the name or the number:\n"
        "1. **Hardware Version** (`hWVersion_astro`)"
    )
    assert answer_is_config_question(q)


def test_answer_is_config_question_ignores_plain_summary():
    assert not answer_is_config_question(
        "Configuration complete for aSTRO25_bom.\n\nProduct Name: APX NEXT",
    )


def test_orphan_question_violates_without_pending():
    answer = "Which value would you like for **Hardware Version**?"
    violations = assert_conversational_invariant(
        answer, {}, run_id="t1", log=False,
    )
    assert violations
    assert "cpq_orphan_question" in violations[0]


def test_pending_clarify_satisfies_invariant():
    answer = numbered_attr_pick_prompt([
        ("hWVersion_astro", "Hardware Version"),
        ("systemKey_astro", "System Key"),
    ])
    session = CpqSession(
        pending_clarify_vns=["hWVersion_astro", "systemKey_astro"],
        pending_clarify_question="change hardware",
        pending_clarify_prompt=answer,
        pending_clarify_asked_turn=3,
        run_id="t2",
    )
    assert has_consumable_pending_state(session.to_dict())
    assert assert_conversational_invariant(
        answer, session.to_dict(), run_id="t2", log=False,
    ) == []


def test_pending_change_no_value_satisfies_invariant():
    answer = "Which value would you like for **Hardware Version**?"
    session = CpqSession(pending_change_no_value_vn="hWVersion_astro")
    assert assert_conversational_invariant(
        answer, session.to_dict(), log=False,
    ) == []


def test_enforce_attaches_violations_key():
    result = {
        "answer": "Which attribute did you mean?",
        "session_data": {"mode": "cpq", "run_id": "x"},
    }
    out = enforce_conversational_invariant(result)
    assert out.get("_cpq_invariant_violations")


def test_match_clarify_reply_offline_label_and_index():
    cands = [
        ("hWVersion_astro", "Hardware Version"),
        ("systemKey_astro", "System Key"),
    ]
    assert match_clarify_reply_offline("Hardware Version", cands) == "hWVersion_astro"
    assert match_clarify_reply_offline("2", cands) == "systemKey_astro"
    assert match_clarify_reply_offline("tell me a joke", cands) is None
