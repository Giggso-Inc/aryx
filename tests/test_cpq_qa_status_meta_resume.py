"""docs/CPQ_QA_RESUME_CONCATENATION_PLAN_2026_08_18.md

Live bug: a session-status/meta-question ("what is the next step for
configuration") asked while a real attribute question is still pending
(e.g. Hardware Version, never answered) got routed through
`_handle_cpq_qa`'s generic graph-QA synthesis path -- which has no
awareness of what's actually pending, and produced an irrelevant,
sometimes-hallucinated answer glued to the correct "Resuming your
configuration..." reminder. Confirmed live twice (different QA-half
wording each time, same contradictory structure).

Fix: a narrow, catalog-agnostic detector (`_is_session_status_meta_question`)
short-circuits `_handle_cpq_qa` straight to the resume block -- skipping
graph-QA synthesis entirely -- only when BOTH the question is genuinely
about session status/process AND something is genuinely pending. Every
other case (real catalog questions, nothing pending) is unchanged.
"""
from __future__ import annotations

from unittest.mock import patch

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _handle_cpq_qa, _is_session_status_meta_question
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


def test_status_meta_question_short_circuits_to_resume_only_when_pending(monkeypatch):
    """The exact reported shape: 'what is the next step for configuration'
    while Hardware Version is pending must answer with ONLY the resume
    block -- no graph-QA preamble, no '---' concatenation."""
    _qa_common_mocks(monkeypatch)
    hw = _attr(1, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H2"))
    session = CpqSession(mode="cpq", product_name="astro")
    session.pending_variables = ["hWVersion_astro"]
    req = AskRequest(question="what is the next step for configuration", workspace_id=1,
                      session_data=session.to_dict())

    with patch("aryx.api.ask_api._synthesise") as mock_synth, \
         patch("aryx.api.ask_api._llm_split_multi_attr_options_query", return_value=None):
        resp = _handle_cpq_qa(req, session, [hw], object())

    mock_synth.assert_not_called()
    assert resp["tools_called"] == ["cpq_qa_status()"]
    assert "Resuming your configuration" in resp["answer"]
    assert "Hardware Version" in resp["answer"]
    # No graph-QA preamble glued in front of the resume block.
    assert resp["answer"].startswith("*Resuming your configuration...*")


def test_status_meta_question_falls_through_when_nothing_pending(monkeypatch):
    """With nothing pending, the short-circuit's own condition can never
    fire -- the same question must fall through to normal QA handling,
    behavior completely unchanged from before this fix."""
    _qa_common_mocks(monkeypatch)
    session = CpqSession(mode="cpq", product_name="astro")
    session.pending_variables = []
    req = AskRequest(question="what is the next step for configuration", workspace_id=1,
                      session_data=session.to_dict())

    with patch("aryx.api.ask_api._extract_terms", return_value=([], 10, 5, 0)), \
         patch("aryx.api.ask_api.gather", return_value=([], [])), \
         patch("aryx.api.ask_api._enrich_with_attributes", lambda entities, *a, **k: entities), \
         patch("aryx.api.ask_api.render_context", return_value=""), \
         patch("aryx.api.ask_api._synthesise",
               return_value=("Your quote is complete.", 20, 15, 0)) as mock_synth, \
         patch("aryx.api.ask_api._llm_split_multi_attr_options_query", return_value=None):
        resp = _handle_cpq_qa(req, session, [], object())

    mock_synth.assert_called_once()
    assert resp["answer"] == "Your quote is complete."


def test_real_catalog_question_while_pending_is_unaffected(monkeypatch):
    """A genuine catalog knowledge question ('what carriers are supported?')
    asked while something is pending must be COMPLETELY unaffected: real
    graph-QA answer AND the resume reminder, both present, exactly as
    before this fix -- that combination is coherent, not the bug."""
    _qa_common_mocks(monkeypatch)
    hw = _attr(1, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H2"))
    session = CpqSession(mode="cpq", product_name="astro")
    session.pending_variables = ["hWVersion_astro"]
    req = AskRequest(question="what carriers are supported?", workspace_id=1,
                      session_data=session.to_dict())

    with patch("aryx.api.ask_api._extract_terms", return_value=([], 10, 5, 0)), \
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


def test_next_hardware_version_phrasing_does_not_misfire_the_detector(monkeypatch):
    """False-positive edge case: a real catalog question using 'next'-
    adjacent phrasing ('what's the next hardware version model after this
    one') must NOT be misdetected as a session-status meta-question -- the
    detector is deliberately phrase-specific, not a bare 'next' keyword."""
    assert not _is_session_status_meta_question(
        "what's the next hardware version model after this one",
    )
    _qa_common_mocks(monkeypatch)
    hw = _attr(1, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H2"))
    session = CpqSession(mode="cpq", product_name="astro")
    session.pending_variables = ["hWVersion_astro"]
    req = AskRequest(question="what's the next hardware version model after this one",
                      workspace_id=1, session_data=session.to_dict())

    with patch("aryx.api.ask_api._extract_terms", return_value=([], 10, 5, 0)), \
         patch("aryx.api.ask_api.gather", return_value=([], [])), \
         patch("aryx.api.ask_api._enrich_with_attributes", lambda entities, *a, **k: entities), \
         patch("aryx.api.ask_api.render_context", return_value=""), \
         patch("aryx.api.ask_api._synthesise",
               return_value=("H2 is the newer model.", 20, 15, 0)) as mock_synth, \
         patch("aryx.api.ask_api._llm_split_multi_attr_options_query", return_value=None):
        resp = _handle_cpq_qa(req, session, [hw], object())

    mock_synth.assert_called_once()
    assert "H2 is the newer model." in resp["answer"]


def test_detector_matches_the_reported_and_repro_d_phrasings():
    """Locks in the exact phrasings confirmed live in the plan doc."""
    assert _is_session_status_meta_question("what is the next step for configuration")
    assert _is_session_status_meta_question("What's next?")
    assert _is_session_status_meta_question("where am I in this process")
    assert _is_session_status_meta_question("what should I do now")
    assert not _is_session_status_meta_question("what carriers are supported?")
    assert not _is_session_status_meta_question("what is the current country")


def test_resume_review_path_is_never_short_circuited(monkeypatch):
    """resume_review=True (the review-summary caller) is a distinct,
    deliberate resume path -- the new short-circuit must never intercept
    it, even if the question text happens to match the meta-question
    patterns."""
    _qa_common_mocks(monkeypatch)
    hw = _attr(1, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H2"))
    session = CpqSession(mode="cpq", product_name="astro")
    session.pending_variables = ["hWVersion_astro"]
    req = AskRequest(question="what is the next step for configuration", workspace_id=1,
                      session_data=session.to_dict())

    with patch("aryx.api.ask_api._extract_terms", return_value=([], 10, 5, 0)), \
         patch("aryx.api.ask_api.gather", return_value=([], [])), \
         patch("aryx.api.ask_api._enrich_with_attributes", lambda entities, *a, **k: entities), \
         patch("aryx.api.ask_api.render_context", return_value=""), \
         patch("aryx.api.ask_api._synthesise",
               return_value=("Here's the graph answer.", 20, 15, 0)) as mock_synth, \
         patch("aryx.api.ask_api._cpq_engine.build_review_prompt",
               return_value="Review: Hardware Version = H1"), \
         patch("aryx.api.ask_api._llm_split_multi_attr_options_query", return_value=None):
        resp = _handle_cpq_qa(req, session, [hw], object(), resume_review=True)

    mock_synth.assert_called_once()
    assert resp["tools_called"] != ["cpq_qa_status()"]
    assert "Review: Hardware Version = H1" in resp["answer"]
