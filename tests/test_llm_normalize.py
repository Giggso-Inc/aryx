"""Tests for aryx.llm_normalize's provider-quirk envelope coercion.

Covers the single-item-list-wraps-a-flat-object quirk (docs/CPQ_LLM_
NORMALIZE_LIST_ENVELOPE_FIX.md) and confirms the pre-existing array-
property wrap behavior is unchanged.
"""
from aryx.llm_normalize import normalize

_FLAT_OBJECT_SCHEMA = {
    "type": "object",
    "properties": {
        "linked": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["linked", "reason"],
}

_ARRAY_PROP_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["entities"],
}


def test_single_item_list_unwraps_to_inner_object_for_flat_schema():
    raw = [{"linked": True, "reason": "shared key"}]
    result = normalize(raw, _FLAT_OBJECT_SCHEMA)
    assert result == {"linked": True, "reason": "shared key"}


def test_bare_object_for_flat_schema_passes_through_unchanged():
    raw = {"linked": True, "reason": "shared key"}
    result = normalize(raw, _FLAT_OBJECT_SCHEMA)
    assert result == raw


def test_multi_item_list_for_flat_schema_is_not_guessed_at():
    raw = [{"linked": True, "reason": "a"}, {"linked": False, "reason": "b"}]
    result = normalize(raw, _FLAT_OBJECT_SCHEMA)
    assert result == raw


def test_empty_list_for_flat_schema_passes_through_unchanged():
    assert normalize([], _FLAT_OBJECT_SCHEMA) == []


def test_single_item_list_of_non_dict_passes_through_unchanged():
    assert normalize(["oops"], _FLAT_OBJECT_SCHEMA) == ["oops"]


def test_array_property_schema_still_wraps_bare_list_as_before():
    raw = [{"name": "a"}, {"name": "b"}]
    result = normalize(raw, _ARRAY_PROP_SCHEMA)
    assert result == {"entities": raw}


def test_non_object_schema_returns_raw_unchanged():
    assert normalize([1, 2, 3], {"type": "array"}) == [1, 2, 3]


def test_missing_schema_returns_raw_unchanged():
    assert normalize([{"a": 1}], None) == [{"a": 1}]
