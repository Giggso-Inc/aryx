"""Live-confirmed root cause (raw XML export APXNext_CnofigData.xml): the
catalog's applicationServicesIntroBundle_astro attribute carries two menu
options with the IDENTICAL display_name "5 Year" but different item_value
("5 YEAR" at order 5, "5 YEARS" at order 8). apply_answer's exact
display-name match returned whichever duplicate came first in option
order, regardless of which literal value any governing rule actually
keys off -- the hiding rule that keeps additionalApplicationServices_astro
visible only recognizes "5 YEARS" (plural), so resolving to "5 YEAR"
(singular) left that attribute stuck hidden even after the customer
answered the duration question.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _attr(**overrides) -> ConfigAttr:
    defaults = dict(
        entity_id=1, variable_name="sampleAttr_astro", display_label="Test Attr",
        required=False, default_value="", options=[], source_id=100,
    )
    defaults.update(overrides)
    return ConfigAttr(**defaults)


def _duration_attr() -> ConfigAttr:
    return _attr(
        variable_name="applicationServicesIntroBundle_astro",
        options=[
            MenuOption(item_value="NONE", display_name="None"),
            MenuOption(item_value="1 YEAR", display_name="1 Year"),
            MenuOption(item_value="5 YEAR", display_name="5 Year"),
            MenuOption(item_value="CUSTOM", display_name="Custom"),
            MenuOption(item_value="5 YEARS", display_name="5 Year"),
        ],
    )


def test_duplicate_display_name_resolves_to_canonical_value_for_known_attr():
    eng = CpqEngine()
    result = eng.apply_answer(_duration_attr(), "5 Year")
    assert result == ("5 YEARS", "5 Year"), (
        "applicationServicesIntroBundle_astro's two '5 Year'-labeled options "
        "must resolve to the literal value ('5 YEARS') that the catalog's "
        "own hiding rule for additionalApplicationServices_astro actually "
        "recognizes -- not whichever duplicate happens to sort first"
    )


def test_unlisted_attr_duplicate_display_name_still_first_match():
    attr = _attr(
        variable_name="someOtherAttr_astro",
        options=[
            MenuOption(item_value="OPT_A", display_name="Same Label"),
            MenuOption(item_value="OPT_B", display_name="Same Label"),
        ],
    )
    eng = CpqEngine()
    result = eng.apply_answer(attr, "Same Label")
    assert result == ("OPT_A", "Same Label"), (
        "an attribute not individually verified in "
        "_DUPLICATE_DISPLAY_NAME_CANONICAL_ITEM_VALUE must keep the prior "
        "first-match behavior unchanged -- this fix only resolves named, "
        "confirmed duplicates, never a generic last-wins/first-wins guess"
    )


def test_non_duplicate_display_name_match_unaffected():
    attr = _attr(
        options=[
            MenuOption(item_value="US", display_name="United States"),
            MenuOption(item_value="CA", display_name="Canada"),
        ],
    )
    eng = CpqEngine()
    result = eng.apply_answer(attr, "Canada")
    assert result == ("CA", "Canada")


def test_exact_display_name_match_wins_over_a_superset_substring_option():
    """PR #214 review (C1): the "Exact display-name match" tier was
    accidentally deleted while adding the duplicate-canonical-value
    special case above it, leaving only an empty comment header. The
    tier below it ("User answer contained in option's display name")
    happened to catch plain exact matches too by coincidence (a string
    is trivially a substring of itself), so most tests still passed --
    but its priority ordering is wrong for options where one display
    name is a superset of another: with options ["Advanced Plus",
    "Advanced"], a reply of exactly "Advanced" must return "Advanced",
    not "Advanced Plus" via "advanced" in "advanced plus". This is the
    live-confirmed root cause the deleted tier existed to prevent."""
    attr = _attr(
        options=[
            MenuOption(item_value="ADV_PLUS", display_name="Advanced Plus"),
            MenuOption(item_value="ADV", display_name="Advanced"),
        ],
    )
    eng = CpqEngine()
    result = eng.apply_answer(attr, "Advanced")
    assert result == ("ADV", "Advanced"), (
        "an exact display-name match must win over a DIFFERENT option "
        "whose display name merely contains the reply as a substring"
    )
