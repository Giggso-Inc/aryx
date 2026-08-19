"""docs/CPQ_QA_RESUME_CONCATENATION_PLAN_2026_08_18.md

Live bug: a session-status/meta-question ("what is the next step for
configuration") asked while a real attribute question is still pending
(e.g. Hardware Version, never answered) got routed through
`_handle_cpq_qa`'s generic graph-QA synthesis path -- which has no
awareness of what's actually pending, and produced an irrelevant,
sometimes-hallucinated answer glued to the correct "Resuming your
configuration..." reminder. Confirmed live twice (different QA-half
wording each time, same contradictory structure).

Fix: `_handle_cpq_qa` short-circuits straight to the resume block --
skipping graph-QA synthesis entirely -- when the SAME universal classifier
it already calls elsewhere for its ambiguity check (`_llm_classify_intent_
universal`) returns `IntentCategory.SESSION_STATUS_QUERY` with
confidence != LOW, AND something is genuinely pending. This replaced an
earlier fixed-phrase-list regex version specifically because a fixed list
under-generalizes across phrasing variants it was never written for --
the classifier call is gated on `session.pending_variables` so it only
runs when a short-circuit could even apply.
"""
from __future__ import annotations

from unittest.mock import patch

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _handle_cpq_qa
from aryx.cpq.intent_schema import Confidence, IntentCategory, IntentResult
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attr(eid, vn, label, *, options=None) -> ConfigAttr:
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=label, required=False,
        default_value="", options=options or [], select_type="single",
    )


def _qa_common_mocks(monkeypatch):
    """Same lightweight monkeypatch pattern used in test_cpq_2026_07_28_fixes.py."""
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "detect_label_collision", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "detect_attr_query", lambda *a, **k: None)
    monkeypatch.setattr(api, "all_types", lambda *a, **k: [])


def _status_result(confidence=Confidence.HIGH) -> IntentResult:
    return IntentResult(
        category=IntentCategory.SESSION_STATUS_QUERY, confidence=confidence,
        rationale="asks about the process, not the catalog",
    )


def _qa_question_result(confidence=Confidence.HIGH) -> IntentResult:
    return IntentResult(
        category=IntentCategory.QA_QUESTION, confidence=confidence,
        rationale="names real catalog content",
    )


def test_status_meta_question_short_circuits_to_resume_only_when_pending(monkeypatch):
    """The exact reported shape: 'what is the next step for configuration'
    while Hardware Version is pending must answer with ONLY the resume
    block -- no graph-QA preamble, no '---' concatenation -- when the
    classifier confidently returns SESSION_STATUS_QUERY."""
    _qa_common_mocks(monkeypatch)
    hw = _attr(1, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H2"))
    session = CpqSession(mode="cpq", product_name="astro")
    session.pending_variables = ["hWVersion_astro"]
    req = AskRequest(question="what is the next step for configuration", workspace_id=1,
                      session_data=session.to_dict())

    with patch("aryx.api.ask_api._llm_classify_intent_universal",
               return_value=(_status_result(), 30, 10)) as mock_classify, \
         patch("aryx.api.ask_api._synthesise") as mock_synth, \
         patch("aryx.api.ask_api._llm_split_multi_attr_options_query", return_value=None):
        resp = _handle_cpq_qa(req, session, [hw], object())

    mock_classify.assert_called_once()
    mock_synth.assert_not_called()
    assert resp["tools_called"] == ["cpq_qa_status()"]
    assert resp["usage"]["prompt_tokens"] == 30
    assert resp["usage"]["completion_tokens"] == 10
    assert "Resuming your configuration" in resp["answer"]
    assert "Hardware Version" in resp["answer"]
    # No graph-QA preamble glued in front of the resume block.
    assert resp["answer"].startswith("*Resuming your configuration...*")


def test_status_meta_question_falls_through_when_nothing_pending(monkeypatch):
    """With nothing pending, the classify call is never even made -- the
    short-circuit's own gating condition prevents it -- and the message
    falls through to normal QA handling, unchanged from before this fix."""
    _qa_common_mocks(monkeypatch)
    session = CpqSession(mode="cpq", product_name="astro")
    session.pending_variables = []
    req = AskRequest(question="what is the next step for configuration", workspace_id=1,
                      session_data=session.to_dict())

    with patch("aryx.api.ask_api._llm_classify_intent_universal") as mock_classify, \
         patch("aryx.api.ask_api._extract_terms", return_value=([], 10, 5, 0)), \
         patch("aryx.api.ask_api.gather", return_value=([], [])), \
         patch("aryx.api.ask_api._enrich_with_attributes", lambda entities, *a, **k: entities), \
         patch("aryx.api.ask_api.render_context", return_value=""), \
         patch("aryx.api.ask_api._synthesise",
               return_value=("Your quote is complete.", 20, 15, 0)) as mock_synth, \
         patch("aryx.api.ask_api._llm_split_multi_attr_options_query", return_value=None):
        resp = _handle_cpq_qa(req, session, [], object())

    mock_classify.assert_not_called()
    mock_synth.assert_called_once()
    assert resp["answer"] == "Your quote is complete."


def test_real_catalog_question_while_pending_is_unaffected(monkeypatch):
    """A genuine catalog knowledge question ('what carriers are supported?')
    asked while something is pending must be COMPLETELY unaffected: real
    graph-QA answer AND the resume reminder, both present, exactly as
    before this fix -- when the classifier correctly returns QA_QUESTION,
    not SESSION_STATUS_QUERY, the short-circuit must not fire."""
    _qa_common_mocks(monkeypatch)
    hw = _attr(1, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H2"))
    session = CpqSession(mode="cpq", product_name="astro")
    session.pending_variables = ["hWVersion_astro"]
    req = AskRequest(question="what carriers are supported?", workspace_id=1,
                      session_data=session.to_dict())

    with patch("aryx.api.ask_api._llm_classify_intent_universal",
               return_value=(_qa_question_result(), 30, 10)), \
         patch("aryx.api.ask_api._extract_terms", return_value=([], 10, 5, 0)), \
         patch("aryx.api.ask_api.gather", return_value=([], [])), \
         patch("aryx.api.ask_api._enrich_with_attributes", lambda entities, *a, **k: entities), \
         patch("aryx.api.ask_api.render_context", return_value=""), \
         patch("aryx.api.ask_api._synthesise",
               return_value=("ATT and Verizon are supported.", 20, 15, 0)) as mock_synth, \
         patch("aryx.api.ask_api._llm_split_multi_attr_options_query", return_value=None):
        resp = _handle_cpq_qa(req, session, [hw], object())

    mock_synth.assert_called_once()
    assert "ATT and Verizon are supported." in resp["answer"]
    assert "Resuming your configuration" in resp["answer"]
    assert "Hardware Version" in resp["answer"]


def test_next_hardware_version_phrasing_does_not_misfire(monkeypatch):
    """False-positive edge case: a real catalog question using 'next'-
    adjacent phrasing ('what's the next hardware version model after this
    one') must NOT be misdetected as a session-status meta-question -- the
    system prompt explicitly instructs the classifier to prefer the
    catalog category in this exact ambiguous-wording case; asserted here
    via the mocked classifier's response (the prompt-content assertion
    below proves the instruction actually reaches the model)."""
    _qa_common_mocks(monkeypatch)
    hw = _attr(1, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H2"))
    session = CpqSession(mode="cpq", product_name="astro")
    session.pending_variables = ["hWVersion_astro"]
    req = AskRequest(question="what's the next hardware version model after this one",
                      workspace_id=1, session_data=session.to_dict())

    with patch("aryx.api.ask_api._llm_classify_intent_universal",
               return_value=(_qa_question_result(), 30, 10)), \
         patch("aryx.api.ask_api._extract_terms", return_value=([], 10, 5, 0)), \
         patch("aryx.api.ask_api.gather", return_value=([], [])), \
         patch("aryx.api.ask_api._enrich_with_attributes", lambda entities, *a, **k: entities), \
         patch("aryx.api.ask_api.render_context", return_value=""), \
         patch("aryx.api.ask_api._synthesise",
               return_value=("H2 is the newer model.", 20, 15, 0)) as mock_synth, \
         patch("aryx.api.ask_api._llm_split_multi_attr_options_query", return_value=None):
        resp = _handle_cpq_qa(req, session, [hw], object())

    mock_synth.assert_called_once()
    assert "H2 is the newer model." in resp["answer"]


def test_low_confidence_session_status_does_not_short_circuit(monkeypatch):
    """A LOW-confidence SESSION_STATUS_QUERY classification must not be
    trusted -- same LOW-confidence-never-trusted discipline every other
    category in this classifier follows (mirrors the AMBIGUOUS branch's
    own confidence gate a few lines below in the same function)."""
    _qa_common_mocks(monkeypatch)
    hw = _attr(1, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H2"))
    session = CpqSession(mode="cpq", product_name="astro")
    session.pending_variables = ["hWVersion_astro"]
    req = AskRequest(question="what now", workspace_id=1, session_data=session.to_dict())

    with patch("aryx.api.ask_api._llm_classify_intent_universal",
               return_value=(_status_result(confidence=Confidence.LOW), 30, 10)), \
         patch("aryx.api.ask_api._extract_terms", return_value=([], 10, 5, 0)), \
         patch("aryx.api.ask_api.gather", return_value=([], [])), \
         patch("aryx.api.ask_api._enrich_with_attributes", lambda entities, *a, **k: entities), \
         patch("aryx.api.ask_api.render_context", return_value=""), \
         patch("aryx.api.ask_api._synthesise",
               return_value=("Fell through to normal QA.", 20, 15, 0)) as mock_synth, \
         patch("aryx.api.ask_api._llm_split_multi_attr_options_query", return_value=None):
        resp = _handle_cpq_qa(req, session, [hw], object())

    mock_synth.assert_called_once()
    assert resp["tools_called"] != ["cpq_qa_status()"]


def test_classifier_failure_falls_through_safely(monkeypatch):
    """The classify call returning None (LLM error/unparseable reply) must
    never break the turn -- falls through to normal QA handling, the same
    fail-closed discipline `_llm_classify_intent_universal` itself already
    guarantees (it returns None on any internal failure)."""
    _qa_common_mocks(monkeypatch)
    hw = _attr(1, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H2"))
    session = CpqSession(mode="cpq", product_name="astro")
    session.pending_variables = ["hWVersion_astro"]
    req = AskRequest(question="what is the next step for configuration", workspace_id=1,
                      session_data=session.to_dict())

    with patch("aryx.api.ask_api._llm_classify_intent_universal",
               return_value=(None, 0, 0)), \
         patch("aryx.api.ask_api._extract_terms", return_value=([], 10, 5, 0)), \
         patch("aryx.api.ask_api.gather", return_value=([], [])), \
         patch("aryx.api.ask_api._enrich_with_attributes", lambda entities, *a, **k: entities), \
         patch("aryx.api.ask_api.render_context", return_value=""), \
         patch("aryx.api.ask_api._synthesise",
               return_value=("Fell through to normal QA.", 20, 15, 0)) as mock_synth, \
         patch("aryx.api.ask_api._llm_split_multi_attr_options_query", return_value=None):
        resp = _handle_cpq_qa(req, session, [hw], object())

    mock_synth.assert_called_once()
    assert resp["tools_called"] != ["cpq_qa_status()"]


def test_session_status_category_present_in_classifier_system_prompt(monkeypatch):
    """The classifier's own system prompt must actually carry the new
    category and its catalog-vs-process disambiguation guidance -- a
    mocked reply alone can't prove the model was ever told this category
    exists."""
    _qa_common_mocks(monkeypatch)
    hw = _attr(1, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H2"))
    session = CpqSession(mode="cpq", product_name="astro")
    session.pending_variables = ["hWVersion_astro"]
    req = AskRequest(question="what is the next step for configuration", workspace_id=1,
                      session_data=session.to_dict())

    with patch("aryx.api.ask_api.llm_runtime.chat",
               return_value=('{"category":"session_status_query","confidence":"high",'
                              '"rationale":"process question"}', 30, 10)) as mock_chat:
        _handle_cpq_qa(req, session, [hw], object())

    sys_prompt = mock_chat.call_args.args[1]
    assert "session_status_query" in sys_prompt
    assert "next hardware version" in sys_prompt


def test_stale_pending_variable_not_in_attrs_falls_through_to_normal_qa(monkeypatch):
    """Negative case: session.pending_variables[0] doesn't resolve against
    any attr actually passed in (a stale/mismatched pending reference --
    e.g. attrs list scoped differently than when pending was set). The
    short-circuit must not return a broken/empty answer here -- it must
    fall through to the normal graph-QA path exactly as before this fix,
    even when the classifier confidently says SESSION_STATUS_QUERY."""
    _qa_common_mocks(monkeypatch)
    session = CpqSession(mode="cpq", product_name="astro")
    session.pending_variables = ["someAttrNotInAttrsList_astro"]
    req = AskRequest(question="what is the next step for configuration", workspace_id=1,
                      session_data=session.to_dict())

    with patch("aryx.api.ask_api._llm_classify_intent_universal",
               return_value=(_status_result(), 30, 10)), \
         patch("aryx.api.ask_api._extract_terms", return_value=([], 10, 5, 0)), \
         patch("aryx.api.ask_api.gather", return_value=([], [])), \
         patch("aryx.api.ask_api._enrich_with_attributes", lambda entities, *a, **k: entities), \
         patch("aryx.api.ask_api.render_context", return_value=""), \
         patch("aryx.api.ask_api._synthesise",
               return_value=("Fell through to normal QA.", 20, 15, 0)) as mock_synth, \
         patch("aryx.api.ask_api._llm_split_multi_attr_options_query", return_value=None):
        resp = _handle_cpq_qa(req, session, [], object())

    mock_synth.assert_called_once()
    assert resp["tools_called"] != ["cpq_qa_status()"]
    assert "Fell through to normal QA." in resp["answer"]


def test_ambiguity_check_reuses_the_session_status_classify_call_not_a_second_one(monkeypatch):
    """PR #213 review finding: the SESSION_STATUS_QUERY check and the
    (flag-gated) ambiguity check both call _llm_classify_intent_universal
    with IDENTICAL arguments -- when both are "in play" on the same turn
    (something pending AND cpq_qa_ambiguity_check_enabled=True AND the
    fast-attr-query path misses), the ambiguity check must reuse the
    first call's result rather than paying for a second, redundant LLM
    round-trip. Uses an AMBIGUOUS result (not SESSION_STATUS_QUERY) so
    the top check does NOT short-circuit, letting execution reach the
    ambiguity block and prove the SAME single call served both."""
    _qa_common_mocks(monkeypatch)
    hw = _attr(1, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H2"))
    session = CpqSession(mode="cpq", product_name="astro")
    session.pending_variables = ["hWVersion_astro"]
    req = AskRequest(question="what about the other thing", workspace_id=1,
                      session_data=session.to_dict())

    ambiguous_result = IntentResult(
        category=IntentCategory.AMBIGUOUS, confidence=Confidence.HIGH,
        clarifying_question="Did you mean the battery or the antenna?",
        rationale="could mean either",
    )
    real_settings = api.get_settings()
    patched_settings = real_settings.model_copy(
        update={"cpq_qa_ambiguity_check_enabled": True})

    with patch("aryx.api.ask_api._llm_classify_intent_universal",
               return_value=(ambiguous_result, 30, 10)) as mock_classify, \
         patch("aryx.api.ask_api.get_settings", lambda: patched_settings), \
         patch("aryx.api.ask_api._extract_terms", return_value=([], 10, 5, 0)), \
         patch("aryx.api.ask_api.gather", return_value=([], [])), \
         patch("aryx.api.ask_api._enrich_with_attributes", lambda entities, *a, **k: entities), \
         patch("aryx.api.ask_api.render_context", return_value=""), \
         patch("aryx.api.ask_api._synthesise") as mock_synth, \
         patch("aryx.api.ask_api._llm_split_multi_attr_options_query", return_value=None):
        resp = _handle_cpq_qa(req, session, [hw], object())

    mock_classify.assert_called_once()
    mock_synth.assert_not_called()
    assert resp["answer"].startswith("Did you mean the battery or the antenna?")


def test_resume_review_path_is_never_short_circuited(monkeypatch):
    """resume_review=True (the review-summary caller) is a distinct,
    deliberate resume path -- the classify call must never even be made
    for it, regardless of question text or pending state."""
    _qa_common_mocks(monkeypatch)
    hw = _attr(1, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H2"))
    session = CpqSession(mode="cpq", product_name="astro")
    session.pending_variables = ["hWVersion_astro"]
    req = AskRequest(question="what is the next step for configuration", workspace_id=1,
                      session_data=session.to_dict())

    with patch("aryx.api.ask_api._llm_classify_intent_universal") as mock_classify, \
         patch("aryx.api.ask_api._extract_terms", return_value=([], 10, 5, 0)), \
         patch("aryx.api.ask_api.gather", return_value=([], [])), \
         patch("aryx.api.ask_api._enrich_with_attributes", lambda entities, *a, **k: entities), \
         patch("aryx.api.ask_api.render_context", return_value=""), \
         patch("aryx.api.ask_api._synthesise",
               return_value=("Here's the graph answer.", 20, 15, 0)) as mock_synth, \
         patch("aryx.api.ask_api._cpq_engine.build_review_prompt",
               return_value="Review: Hardware Version = H1"), \
         patch("aryx.api.ask_api._llm_split_multi_attr_options_query", return_value=None):
        resp = _handle_cpq_qa(req, session, [hw], object(), resume_review=True)

    mock_classify.assert_not_called()
    mock_synth.assert_called_once()
    assert resp["tools_called"] != ["cpq_qa_status()"]
    assert "Review: Hardware Version = H1" in resp["answer"]
