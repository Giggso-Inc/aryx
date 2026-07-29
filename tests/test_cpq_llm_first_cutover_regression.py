"""Regression checks (T8-T10 from docs/CPQ_LLM_FIRST_FULL_CUTOVER_PLAN.md
section 5.4) against the ACTUAL intent_gateway.py implementation on
dev-rv, not the never-built _llm_classify_intent_universal design the
plan doc's T1-T18 were originally written against.

Each test proves the gateway's real mechanism doesn't reopen one of the
3 specific already-fixed bugs the plan doc flagged as highest priority.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

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
