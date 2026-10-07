"""A shared option label resolves when one value's own code is what was typed.

Regression for the live defect (ws 1267, 2026-10-07): the product selector has
two options displaying the same label, one storing the product's own code and
one storing a variant's. `extract_catalog_hints` refused to hint whenever a
phrase mapped to 2+ values of the same attribute, so nothing was hinted, the
model leaf stayed ambiguous, and the customer was shown every product in the
family (132 of them) instead of a narrowed list.

The rule: on the product selector only, when exactly one tied value's own code
normalizes to the matched phrase, prefer that value -- unless the question also
evidences a longer sibling code, in which case the wording supports the variant
and nothing is picked. Every other attribute keeps the never-guess outcome.

Names below are generic shapes, never real product or model codes, so these
cases test the rule rather than one catalog's values.
"""
from __future__ import annotations

import pytest

from aryx.cpq.catalog_hints_tie import exact_code_owner, single_entry
from aryx.cpq.catalog_profile import PRODUCT_LITERAL

OTHER = "someOtherAttr_astro"


def test_single_distinct_value_is_returned_unchanged():
    assert single_entry([(PRODUCT_LITERAL, "THINGONE")], "thingone") == (PRODUCT_LITERAL, "THINGONE")


def test_single_distinct_value_on_a_non_product_attr_is_also_unchanged():
    # Not a tie at all, so the product-selector gate does not apply.
    assert single_entry([(OTHER, "THINGONE")], "thingone") == (OTHER, "THINGONE")


def test_tie_resolves_to_the_value_whose_code_is_the_typed_phrase():
    entries = [(PRODUCT_LITERAL, "THINGONE"), (PRODUCT_LITERAL, "THINGONEVARIANT")]
    assert single_entry(entries, "thingone") == (PRODUCT_LITERAL, "THINGONE")


def test_tie_resolves_to_the_variant_when_the_variant_code_is_typed():
    entries = [(PRODUCT_LITERAL, "THINGONE"), (PRODUCT_LITERAL, "THINGONEVARIANT")]
    assert single_entry(entries, "thingonevariant") == (PRODUCT_LITERAL, "THINGONEVARIANT")


def test_a_tie_on_a_non_product_attribute_still_never_guesses():
    """Review finding: the rule was measured on the product selector only.

    Live counts (ws 1267): the selector has 28 tied labels, 26 resolvable; all
    other menu attributes together have 251 tied labels, 220 resolvable. Those
    220 have no evidence behind them, so the rule must not reach them.
    """
    entries = [(OTHER, "THINGONE"), (OTHER, "THINGONEVARIANT")]
    assert single_entry(entries, "thingone") is None


def test_a_tie_spanning_product_and_another_attribute_never_guesses():
    entries = [(PRODUCT_LITERAL, "THINGONE"), (OTHER, "THINGONEVARIANT")]
    assert single_entry(entries, "thingone") is None


def test_the_variant_being_evidenced_in_the_question_blocks_the_base_pick():
    """Review finding: "upgrade my THING ONE with variant" must not pick the base.

    The sibling code extends the matched phrase, and the rest of it appears in
    the question, so the wording supports the variant. Before this guard the
    base value was filled silently where the old code simply asked.
    """
    entries = [(PRODUCT_LITERAL, "THINGONE"), (PRODUCT_LITERAL, "THINGONEVARIANT")]
    q = "iwanttoupgrademythingoneradiowithvariant"
    assert single_entry(entries, "thingone", q) is None


def test_the_base_pick_stands_when_the_variant_is_not_evidenced():
    entries = [(PRODUCT_LITERAL, "THINGONE"), (PRODUCT_LITERAL, "THINGONEVARIANT")]
    q = "iwantquotethingoneforus"
    assert single_entry(entries, "thingone", q) == (PRODUCT_LITERAL, "THINGONE")


def test_tie_with_no_exact_code_still_refuses_to_guess():
    entries = [(PRODUCT_LITERAL, "THING ONE MULTI"), (PRODUCT_LITERAL, "THINGONEXVARIANT")]
    assert single_entry(entries, "thingoneallband") is None


def test_tie_with_two_exact_codes_still_refuses_to_guess():
    entries = [(PRODUCT_LITERAL, "THING-ONE"), (PRODUCT_LITERAL, "THING ONE")]
    assert single_entry(entries, "thingone") is None


def test_exact_code_owner_is_case_and_punctuation_insensitive():
    assert exact_code_owner({(PRODUCT_LITERAL, "Thing-One")}, "thingone") == (PRODUCT_LITERAL, "Thing-One")


def test_duplicate_identical_entries_are_not_a_tie():
    entries = [(PRODUCT_LITERAL, "THINGONE"), (PRODUCT_LITERAL, "THINGONE")]
    assert single_entry(entries, "thingone") == (PRODUCT_LITERAL, "THINGONE")


@pytest.mark.parametrize("phrase", ["", "nomatch"])
def test_no_entry_matching_the_phrase_returns_none(phrase):
    entries = [(PRODUCT_LITERAL, "THINGONE"), (PRODUCT_LITERAL, "THINGONEVARIANT")]
    assert single_entry(entries, phrase) is None
