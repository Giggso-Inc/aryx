"""Regression checks (T8-T10 from docs/CPQ_LLM_FIRST_FULL_CUTOVER_PLAN.md
section 5.4) against the ACTUAL intent_gateway.py implementation on
dev-rv, not the never-built _llm_classify_intent_universal design the
plan doc's T1-T18 were originally written against.

Each test proves the gateway's real mechanism doesn't reopen one of the
3 specific already-fixed bugs the plan doc flagged as highest priority.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.api.ask_api import _is_change_value_decline, _llm_split_compound_change_and_question
from aryx.cpq.intent_gateway import (
    _format_candidates_for_prompt,
    build_candidate_bundles,
    classify_intent,
    clear_gateway_cache,
    resolve_value_from_ref,
)
from aryx.cpq.intent_schema import (
    Confidence,
    GatewayIntentResult,
    IntentCategory,
    validate_gateway_quarantine,
)
from aryx.cpq.state import CpqSession
from tests.test_cpq_intent_gateway import _attr


def test_t8_label_collision_prompt_includes_current_value_for_disambiguation():
    """T8: 'the one that currently has jacket magnetic mount' needs each
    candidate's CURRENT VALUE in the prompt to disambiguate — the same
    fix already proven this session for _llm_resolve_label_collision.
    Confirms the gateway's prompt-building carries this context too.
    """
    session = CpqSession()
    session.filled = {
        "mountType_a": "jacket_magnetic",
        "mountType_b": "shirt_clip",
    }
    attrs = [
        _attr("mountType_a", "Mounting Option A",
              [("jacket_magnetic", "Jacket Magnetic Mount")]),
        _attr("mountType_b", "Mounting Option B",
              [("shirt_clip", "Shirt Clip Mount")]),
    ]
    bundles = build_candidate_bundles(
        attrs, session, "clear the one that currently has jacket magnetic mount",
    )
    prompt = _format_candidates_for_prompt(bundles, session)
    assert "current='jacket_magnetic'" in prompt
    assert "current='shirt_clip'" in prompt


def test_t9_multi_fact_adjacency_delegates_to_deterministic_multi_detector():
    """T9: '25 devices at 25 locations' — same value for two sibling
    attrs. The gateway does NOT ask the LLM to extract both values
    itself; it only names ONE target and checks membership against
    detect_change_requests_multi's own (already-correct, adjacency-aware)
    result set. Confirms that delegation actually works end to end:
    the deterministic detector resolves both values distinctly, and the
    gateway's single-target agreement check doesn't block dispatch.
    """
    clear_gateway_cache()
    session = CpqSession()
    session.product_name = "astro"
    devices = _attr("deviceCount_a", "Device Count")
    locations = _attr("locationCount_a", "Location Count")
    attrs = [devices, locations]
    engine = MagicMock()
    engine.detect_change_request.return_value = None
    # Deterministic multi-detector already disambiguates both facts —
    # this is the existing, unchanged, adjacency-aware logic; the
    # gateway must not need to reproduce it.
    engine.detect_change_requests_multi.return_value = [
        (devices, "25"), (locations, "25"),
    ]
    engine.detect_change_target_without_value.return_value = None
    engine.detect_multi_select_removal.return_value = None
    engine.detect_bulk_quantity_change.return_value = None

    good_json = (
        '{"intent_category":"change_requests_multi","confidence":"high",'
        '"variable_name":"deviceCount_a","value_ref":null,'
        '"evidence_span":"25 devices at 25 locations",'
        '"rationale":"names one of the two facts"}'
    )
    with patch(
        "aryx.cpq.intent_gateway._pinned_chat",
        return_value=(good_json, 10, 5),
    ):
        decision = classify_intent(
            "set 25 devices at 25 locations", attrs, session, engine,
            workspace_id=1,
        )
    # Agreement holds because deviceCount_a IS in the deterministic
    # multi-detector's result set — the gateway never had to resolve
    # the adjacency itself, so it can't get it wrong.
    assert decision.action == "dispatch"
    assert decision.result.variable_name == "deviceCount_a"


def test_t10_semantic_pending_answer_resolves_via_index_not_literal_text():
    """T10: 'the cheap one' (semantic, not a literal option label) —
    value_ref is an index into the candidate list, so the LLM's semantic
    reasoning resolves it regardless of exact wording; evidence_span
    only has to be grounded in the QUESTION (not the catalog text), so
    quoting the user's own phrase satisfies quarantine.
    """
    result = GatewayIntentResult(
        intent_category=IntentCategory.CHANGE_REQUEST,
        confidence=Confidence.HIGH,
        variable_name="priceTier_a",
        value_ref=0,  # the cheap option happens to be candidate index 0
        evidence_span="the cheap one",
        rationale="semantic match to lowest-priced tier",
    )
    quarantined = validate_gateway_quarantine(
        result,
        "I'll go with the cheap one",
        {"priceTier_a"},
        {"priceTier_a": 2},
    )
    assert quarantined.intent_category == IntentCategory.CHANGE_REQUEST
    assert quarantined.variable_name == "priceTier_a"

    # Standard Tier is conceptually "the cheap one" — resolved by index,
    # never by matching "cheap" against any option's literal display name.
    price_attr = _attr(
        "priceTier_a", "Price Tier",
        [("standard", "Standard Tier"), ("premium", "Premium Tier")],
    )
    session = CpqSession()
    # Realistic context: the system had JUST asked about this attribute,
    # which is why "the cheap one" is understood as answering it at all.
    session.pending_variables = ["priceTier_a"]
    bundles = build_candidate_bundles(
        [price_attr], session, "I'll go with the cheap one",
    )
    display, item_value = resolve_value_from_ref(quarantined, bundles)
    assert item_value == "standard"
    assert display == "Standard Tier"


# ── docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §7 ────────────────
# The residual risk flagged when that fix landed: could the LLM-first split
# ever mis-classify a genuine MULTI-CHANGE message ("change X and change Y",
# no separate question at all — already correctly owned by
# CHANGE_REQUESTS_MULTI) as a change+question compound, discarding half of it
# into a nonsense Q&A answer? These tests pin the safety net: the function's
# own prompt instructs the model not to split that case, and its validator
# fails closed (returns None) whenever the model's JSON doesn't cleanly
# provide BOTH a non-empty change_text and a non-empty question_text.

def test_compound_split_returns_none_for_multi_change_not_compound():
    """Multi-change message ("change hardware version and system key") —
    the model correctly reports is_compound=false (both are changes, no
    separate question) — must NOT be split."""
    fake_reply = '{"is_compound": false, "change_text": "", "question_text": ""}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _llm_split_compound_change_and_question(
            "change hardware version and system key", workspace_id=1,
        )
    assert result is None


def test_compound_split_resolves_genuine_change_and_question():
    """Genuine compound message DOES split into two self-contained
    requests when the model reports is_compound=true with both fields."""
    fake_reply = (
        '{"is_compound": true, '
        '"change_text": "make product APX NEXT XE (4G LTE+5G)", '
        '"question_text": "what is the carrier being selected"}'
    )
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _llm_split_compound_change_and_question(
            "make product as APX NEXT XE (4G LTE+5G) and what is the "
            "carrier being selected",
            workspace_id=1,
        )
    assert result == (
        "make product APX NEXT XE (4G LTE+5G)",
        "what is the carrier being selected",
    )


def test_compound_split_fails_closed_on_missing_change_text():
    """is_compound=true but change_text empty — must fail closed (None),
    never split with a blank half."""
    fake_reply = (
        '{"is_compound": true, "change_text": "", '
        '"question_text": "what is the carrier being selected"}'
    )
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _llm_split_compound_change_and_question(
            "make product as X and what is the carrier being selected",
            workspace_id=1,
        )
    assert result is None


def test_compound_split_fails_closed_on_malformed_json():
    """LLM call returns garbage — must fail closed (None), never crash
    the turn."""
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=("not json", 1, 1)):
        result = _llm_split_compound_change_and_question(
            "make product as X and what is the carrier being selected",
            workspace_id=1,
        )
    assert result is None


# ── docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §10 (QA issue #2) ─
# Learned directly from §6's regex miss ("wanted" vs "want") — these pin
# the stemmed forms so the same class of gap can't reopen here.

def test_change_value_decline_matches_common_phrasings():
    for phrase in [
        "I don't want to change product",
        "I don't want to change it",
        "do not want to change this",
        "no changes please",
        "not changing anything",
        "leave it as is",
        "keep it the way it is",
        "never mind",
        "nevermind",
        "cancel that",
        "cancel this",
        "skip this",
    ]:
        assert _is_change_value_decline(phrase), f"should match: {phrase!r}"


def test_change_value_decline_matches_stemmed_verb_forms():
    """The earlier regex attempt (§6) missed 'wanted' vs 'want' — pin the
    stemmed forms here so this decline check can't repeat that mistake."""
    for phrase in [
        "I don't wanted to change the attribute",
        "I don't wanting to change this",
    ]:
        assert _is_change_value_decline(phrase), f"should match: {phrase!r}"


def test_change_value_decline_does_not_match_bare_no_or_real_values():
    """Bare 'no' must NOT match — it's a legitimate value for yes/no-shaped
    attrs, and a real attempted value must still reach apply_answer."""
    for phrase in ["no", "No", "H45", "APX NEXT XE", "ATT/FirstNet"]:
        assert not _is_change_value_decline(phrase), f"must not match: {phrase!r}"
