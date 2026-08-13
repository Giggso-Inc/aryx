"""LLM-first scope-reply classification — docs/CPQ_PRODUCT_SCOPE_LLM_
FIRST_PLAN_2026_08_13.md.

Live bug this closes: "go further" replied to a pending "Product —
choose one" question got the same content-free "I didn't get X for
Product" re-ask as a garbled product name -- string-similarity alone
(resolve_against_scope) has no way to recognize "the customer wants to
move past this question" as distinct from "the customer tried and
failed to name a product."

Fix: _llm_classify_scope_reply runs FIRST, classifying a reply as
"candidate" (points at one real option), "skip" (asking to move past
this question), or "unrelated" (neither). _resolve_scope_reply is the
single integration point: on "candidate", the LLM's guess is
independently validated against the real candidate list via the
unchanged resolve_against_scope ladder before being trusted -- never a
free-text value handed straight through. On "skip", "unrelated", or any
LLM failure, behavior falls through to the exact same deterministic
ladder as before this change.
"""
from __future__ import annotations

from unittest.mock import patch

import aryx.api.ask_api as api
from aryx.api.ask_api import (
    AskRequest,
    _build_scope_family_only_response,
    _build_scope_skip_response,
    _llm_classify_scope_reply,
    _resolve_scope_reply,
    _run_cpq_turn,
)
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attr(eid, vn, label, *, options=None) -> ConfigAttr:
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=label, required=False,
        default_value="", options=options or [], select_type="single",
    )


def _chat_json(reply_json: str):
    return (reply_json, 10, 5)


# ═══════════════════════════════════════════════════════════════════════
# _llm_classify_scope_reply / _resolve_scope_reply — in isolation
# ═══════════════════════════════════════════════════════════════════════

def test_llm_classifies_and_resolves_a_specific_candidate():
    cands = [
        "APX NEXT All Band", "APX NEXT XE All Band",
        "APX NEXT International (Federal)",
    ]
    with patch.object(
        api.llm_runtime, "chat",
        return_value=_chat_json(
            '{"outcome": "candidate", "guess": "APX NEXT International (Federal)"}',
        ),
    ):
        outcome, guess = _llm_classify_scope_reply(
            "the international one", cands, "Product", CpqSession(), 1,
        )
    assert outcome == "candidate"
    assert guess == "APX NEXT International (Federal)"
    with patch.object(
        api.llm_runtime, "chat",
        return_value=_chat_json(
            '{"outcome": "candidate", "guess": "APX NEXT International (Federal)"}',
        ),
    ):
        res = _resolve_scope_reply(
            "the international one", cands, "Product", CpqSession(), 1,
        )
    assert res != "skip"
    assert res.matched == "APX NEXT International (Federal)"


def test_llm_classifies_go_further_as_skip():
    cands = ["APX NEXT All Band", "APX NEXT XE All Band"]
    with patch.object(
        api.llm_runtime, "chat",
        return_value=_chat_json('{"outcome": "skip", "guess": null}'),
    ):
        outcome, guess = _llm_classify_scope_reply(
            "go further", cands, "Product", CpqSession(), 1,
        )
    assert outcome == "skip"
    assert guess is None
    with patch.object(
        api.llm_runtime, "chat",
        return_value=_chat_json('{"outcome": "skip", "guess": null}'),
    ):
        res = _resolve_scope_reply("go further", cands, "Product", CpqSession(), 1)
    assert res == "skip"


def test_skip_response_asks_instead_of_guessing_and_uses_distinct_tag():
    cands = ["APX NEXT All Band", "APX NEXT XE All Band"]
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom")
    req = AskRequest(question="go further", workspace_id=1, session_data=session.to_dict())
    resp = _build_scope_skip_response(req, session, cands, "Product")
    assert resp["tools_called"] == ["cpq_scope_skip_declined()"]
    assert "APX NEXT All Band" in resp["answer"]
    assert "APX NEXT XE All Band" in resp["answer"]
    # Never silently picks one of the candidates as a default.
    assert "→" not in resp["answer"]


def test_llm_candidate_guess_not_in_real_list_falls_through_to_deterministic():
    cands = ["APX NEXT All Band", "APX NEXT XE All Band"]
    with patch.object(
        api.llm_runtime, "chat",
        return_value=_chat_json(
            '{"outcome": "candidate", "guess": "Some Hallucinated Product"}',
        ),
    ):
        res = _resolve_scope_reply(
            "the all band one", cands, "Product", CpqSession(), 1,
        )
    # Falls through to the deterministic ladder on the ORIGINAL reply --
    # "the all band one" partially/fuzzily matches both All Band options,
    # so this must not silently accept the hallucinated guess.
    assert res != "skip"
    assert res.matched != "Some Hallucinated Product"


def test_llm_call_failure_falls_through_to_deterministic_miss():
    cands = ["APX NEXT All Band", "APX NEXT XE All Band"]
    with patch.object(api.llm_runtime, "chat", side_effect=RuntimeError("boom")):
        outcome, guess = _llm_classify_scope_reply(
            "the international one", cands, "Product", CpqSession(), 1,
        )
    assert outcome == "unrelated"
    assert guess is None
    with patch.object(api.llm_runtime, "chat", side_effect=RuntimeError("boom")):
        res = _resolve_scope_reply(
            "zzznotreal", cands, "Product", CpqSession(), 1,
        )
    assert res != "skip"
    assert res.matched is None
    assert res.tier == "miss"


def test_i_want_quote_for_apx_next_radios_is_family_only_not_a_generic_miss():
    """Names the family but no specific variant -- classified
    "family_only", distinct from a genuine "unrelated" miss, so the
    customer gets told plainly to pick a specific option instead of the
    generic "I didn't get X" wording."""
    cands = [
        "APX NEXT All Band", "APX NEXT XE All Band", "APX NEXT Single Band",
        "APX NEXT XE Single Band", "APX NEXT International (Federal)",
        "APX NEXT XN All Band", "APX NEXT XN Single Band",
    ]
    with patch.object(
        api.llm_runtime, "chat",
        return_value=_chat_json('{"outcome": "family_only", "guess": null}'),
    ):
        res = _resolve_scope_reply(
            "I want quote for APX Next radios", cands, "Product", CpqSession(), 1,
        )
    assert res == "family_only"


def test_family_only_response_tells_customer_to_pick_a_specific_option():
    cands = ["APX NEXT All Band", "APX NEXT XE All Band"]
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom")
    req = AskRequest(
        question="I want quote for APX Next radios", workspace_id=1,
        session_data=session.to_dict(),
    )
    resp = _build_scope_family_only_response(req, session, cands, "Product")
    assert resp["tools_called"] == ["cpq_scope_family_only()"]
    assert "select the specific" in resp["answer"].lower()
    assert "APX NEXT All Band" in resp["answer"]
    assert "APX NEXT XE All Band" in resp["answer"]
    # Never says the reply itself failed to match anything.
    assert "didn't get" not in resp["answer"].lower()


def test_a_variant_embedded_in_a_longer_sentence_still_resolves_as_candidate():
    """A specific variant mentioned anywhere in the reply must win over
    treating the message as merely naming the family -- owner directive:
    if the product name is already present in the query, it must be
    detected, not deferred to family_only."""
    cands = [
        "APX NEXT All Band", "APX NEXT XE All Band", "APX NEXT Single Band",
    ]
    with patch.object(
        api.llm_runtime, "chat",
        return_value=_chat_json(
            '{"outcome": "candidate", "guess": "APX NEXT All Band"}',
        ),
    ):
        res = _resolve_scope_reply(
            "I want a quote for the APX Next All Band radios please",
            cands, "Product", CpqSession(), 1,
        )
    assert res != "skip"
    assert res != "family_only"
    assert res.matched == "APX NEXT All Band"


# ═══════════════════════════════════════════════════════════════════════
# Integration: a real pending "Product" question, end to end
# ═══════════════════════════════════════════════════════════════════════

def test_go_further_on_a_pending_product_question_asks_instead_of_reasking_the_same_list(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_recommendation_and_constraint_rules",
        lambda *a, **k: ([], []),
    )
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])

    scoped = ["APX NEXT All Band", "APX NEXT XE All Band", "APX NEXT International (Federal)"]
    product = _attr(1, "productSelectionProduct_all", "Product", options=_opt(*scoped))
    monkeypatch.setattr(
        api._cpq_engine, "load_product_config",
        lambda *a, **k: ([product], "aSTRO25_bom"),
    )
    monkeypatch.setattr(
        api._cpq_engine, "apply_constraint_rules",
        lambda *a, **k: {1: [o.item_value for o in product.options]},
    )

    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        pending_variables=["productSelectionProduct_all"],
        pending_scope_kind="product_options",
        pending_scope_candidates=scoped,
        pending_scope_attr_vn="productSelectionProduct_all",
        status="configuring", turn=3,
    )
    req = AskRequest(question="go further", workspace_id=1, session_data=session.to_dict())
    with patch.object(
        api.llm_runtime, "chat",
        return_value=_chat_json('{"outcome": "skip", "guess": null}'),
    ):
        resp = _run_cpq_turn(req, object())
    assert resp["tools_called"] == ["cpq_scope_skip_declined()"]
    assert "can't skip it yet" in resp["answer"]
    for opt in scoped:
        assert opt in resp["answer"]
