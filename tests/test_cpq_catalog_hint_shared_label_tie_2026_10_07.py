"""A shared option label resolves when one value's own code is what was typed.

Regression for the live defect (ws 1267, 2026-10-07): the product selector has
two options displaying the same label, one storing the product's own code and
one storing a variant's. `extract_catalog_hints` refused to hint whenever a
phrase mapped to 2+ values of the same attribute, so nothing was hinted, the
model leaf stayed ambiguous, and the customer was shown every product in the
family (132 of them) instead of a narrowed list.

The rule restored here: when exactly one tied value's own code normalizes to
the matched phrase, the customer typed that code and no guess is involved.
Zero or 2+ such values keep the never-guess outcome.

Names below are generic shapes, never real product or model codes, so these
cases test the rule rather than one catalog's values.
"""
from __future__ import annotations

import pytest

from aryx.cpq.catalog_hints_tie import exact_code_owner, single_entry

VN = "productSelectorStub"


def test_single_distinct_value_is_returned_unchanged():
    entries = [(VN, "THINGONE")]
    assert single_entry(entries, "thingone") == (VN, "THINGONE")


def test_tie_resolves_to_the_value_whose_code_is_the_typed_phrase():
    # Both display "Thing One"; the customer typed exactly the plain code.
    entries = [(VN, "THINGONE"), (VN, "THINGONEVARIANT")]
    assert single_entry(entries, "thingone") == (VN, "THINGONE")


def test_tie_resolves_to_the_variant_when_the_variant_code_is_typed():
    entries = [(VN, "THINGONE"), (VN, "THINGONEVARIANT")]
    assert single_entry(entries, "thingonevariant") == (VN, "THINGONEVARIANT")


def test_tie_with_no_exact_code_still_refuses_to_guess():
    # Neither stored code equals the shared label -- the real "All Band" case.
    entries = [(VN, "THING ONE MULTI"), (VN, "THINGONEXVARIANT")]
    assert single_entry(entries, "thingoneallband") is None


def test_tie_with_two_exact_codes_still_refuses_to_guess():
    # Two values whose codes normalize identically: genuinely ambiguous.
    entries = [(VN, "THING-ONE"), (VN, "THING ONE")]
    assert single_entry(entries, "thingone") is None


def test_exact_code_owner_is_case_and_punctuation_insensitive():
    entries = {(VN, "Thing-One")}
    assert exact_code_owner(entries, "thingone") == (VN, "Thing-One")


def test_duplicate_identical_entries_are_not_a_tie():
    # The same pair listed twice is one real value, not an ambiguity.
    entries = [(VN, "THINGONE"), (VN, "THINGONE")]
    assert single_entry(entries, "thingone") == (VN, "THINGONE")


@pytest.mark.parametrize("phrase", ["", "nomatch"])
def test_no_entry_matching_the_phrase_returns_none(phrase):
    entries = [(VN, "THINGONE"), (VN, "THINGONEVARIANT")]
    assert single_entry(entries, phrase) is None
