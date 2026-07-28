"""Phase 0 coverage — docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md.

Pins the structured intent-classification contract (src/aryx/cpq/
intent_schema.py) before any classifier is wired into the live turn flow
(Phase 1+). Not a regression test for existing behavior — this schema
isn't consumed by _run_cpq_turn yet; these tests only guarantee the
parse/validate chokepoint (parse_intent_result) behaves per the plan
doc's mitigation #7 ("one shared parse-and-validate wrapper... not each
one hand-rolling its own try/except") before anything is built on top of
it.
"""
from __future__ import annotations

from aryx.cpq.intent_schema import (
    ChangeTarget,
    Confidence,
    IntentCategory,
    IntentResult,
    INTENT_RESULT_JSON_SCHEMA,
    parse_intent_result,
)


def test_every_category_value_is_a_string_enum_member():
    # The JSON schema's enum list is derived from IntentCategory directly
    # (schema/dataclass drift is exactly what mitigation #7 exists to
    # prevent) -- this just pins that derivation stays correct.
    schema_values = INTENT_RESULT_JSON_SCHEMA["properties"]["category"]["enum"]
    assert schema_values == [c.value for c in IntentCategory]


def test_valid_single_target_change_request_parses():
    raw = {
        "category": "change_request",
        "confidence": "high",
        "target": {
            "target_description": "the Solution Type field",
            "new_value_description": "RadioCentral with CPS",
        },
        "rationale": "user named an attribute and a new value",
    }
    result = parse_intent_result(raw)
    assert result is not None
    assert result.category == IntentCategory.CHANGE_REQUEST
    assert result.confidence == Confidence.HIGH
    assert result.target == ChangeTarget(
        target_description="the Solution Type field",
        new_value_description="RadioCentral with CPS",
    )
    assert result.targets == []


def test_valid_multi_target_parses_into_targets_list():
    raw = {
        "category": "change_requests_multi",
        "confidence": "medium",
        "targets": [
            {"target_description": "primary service type", "new_value_description": "Comprehensive"},
            {"target_description": "solution type", "new_value_description": None},
        ],
        "rationale": "two distinct change targets named in one message",
    }
    result = parse_intent_result(raw)
    assert result is not None
    assert result.category == IntentCategory.CHANGE_REQUESTS_MULTI
    assert len(result.targets) == 2
    assert result.targets[0].target_description == "primary service type"
    assert result.targets[1].new_value_description is None


def test_ambiguous_without_clarifying_question_fails_to_parse():
    # Mitigation #4 in the plan doc: AMBIGUOUS must always carry a
    # clarifying_question -- a category claiming "I don't know" with
    # nothing to ask back is itself a malformed classification.
    raw = {
        "category": "ambiguous",
        "confidence": "low",
        "rationale": "couldn't tell which attribute this refers to",
    }
    assert parse_intent_result(raw) is None


def test_ambiguous_with_clarifying_question_parses():
    raw = {
        "category": "ambiguous",
        "confidence": "low",
        "clarifying_question": "Which coverage option did you mean?",
        "rationale": "two plausible attrs, no clear signal which one",
    }
    result = parse_intent_result(raw)
    assert result is not None
    assert result.category == IntentCategory.AMBIGUOUS
    assert result.clarifying_question == "Which coverage option did you mean?"


def test_unknown_category_fails_closed():
    raw = {"category": "delete_everything", "confidence": "high", "rationale": "n/a"}
    assert parse_intent_result(raw) is None


def test_unknown_confidence_fails_closed():
    raw = {"category": "approval", "confidence": "certain", "rationale": "n/a"}
    assert parse_intent_result(raw) is None


def test_missing_required_fields_fails_closed():
    assert parse_intent_result({}) is None
    assert parse_intent_result({"category": "approval"}) is None


def test_malformed_target_shape_fails_closed():
    # A target missing target_description (the one field the deterministic
    # resolver absolutely needs) must not silently become target=None --
    # that would look identical to "no target for this category" and
    # could route a change_request through as if it had none.
    raw = {
        "category": "change_request",
        "confidence": "high",
        "target": {"new_value_description": "Comprehensive"},
        "rationale": "n/a",
    }
    assert parse_intent_result(raw) is None


def test_response_mode_and_quantity_fields_round_trip():
    raw = {
        "category": "response_mode_request",
        "confidence": "high",
        "response_mode": "json",
        "rationale": "user asked to see the payload",
    }
    result = parse_intent_result(raw)
    assert result is not None
    assert result.response_mode == "json"

    raw2 = {
        "category": "bulk_quantity_change",
        "confidence": "high",
        "target": {"target_description": "every mounting type row"},
        "quantity_description": "67",
        "rationale": "user asked to set all quantities at once",
    }
    result2 = parse_intent_result(raw2)
    assert result2 is not None
    assert result2.quantity_description == "67"


def test_categories_cover_every_existing_detector_and_no_collision_categories():
    # Plan doc §5 refinement: label_collision/change_request_collision are
    # deliberately excluded -- collisions are discovered by the
    # deterministic RESOLUTION layer, not classified upfront by the LLM.
    names = {c.value for c in IntentCategory}
    assert "label_collision" not in names
    assert "change_request_collision" not in names
    # One category per existing regex detector this classifier is meant
    # to eventually replace as the router (plan doc §5 point 4).
    expected_detector_mirrors = {
        "product_mention", "response_mode_request", "multi_select_removal",
        "attr_activation", "attr_clear", "bulk_quantity_change", "approval",
        "qa_question", "change_request", "change_target_without_value",
        "change_requests_multi", "attr_query",
    }
    assert expected_detector_mirrors <= names
    assert "ambiguous" in names
    assert "out_of_scope" in names
