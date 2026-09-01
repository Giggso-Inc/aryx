"""Tests for CpqEngine.apply_answer's duration/unit abbreviation
normalization — docs/CPQ_AMBIGUOUS_CLARIFY_DISCARDS_RESOLVED_EVIDENCE_
PLAN_2026_08_21.md.

Live-confirmed bug: "2Yrs" (no space, abbreviated unit) matched none of
apply_answer's existing tiers against a real "2 Year" option — "2yrs"
tokenizes as one alphanumeric run sharing zero words with "2"+"year".
Fixed with a narrow, scoped regex normalization (digit directly followed
by "yr"/"yrs") applied before the existing matching tiers run.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*pairs: tuple[str, str]) -> list[MenuOption]:
    return [MenuOption(item_value=iv, display_name=dn, order=i) for i, (iv, dn) in enumerate(pairs)]


def _duration_attr() -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="anywhereProgramming_astro", display_label="SmartProgramming",
        required=False, default_value="", options=_menu(("1 YEAR", "1 Year"), ("2 YEAR", "2 Year")),
    )


def test_no_space_yrs_abbreviation_matches_real_option():
    engine = CpqEngine()
    result = engine.apply_answer(_duration_attr(), "Set SmartProgramming to 2Yrs")
    assert result == ("2 YEAR", "2 Year")


def test_spaced_yrs_abbreviation_matches_real_option():
    engine = CpqEngine()
    result = engine.apply_answer(_duration_attr(), "Set SmartProgramming to 2 Yrs")
    assert result == ("2 YEAR", "2 Year")


def test_singular_yr_abbreviation_matches_real_option():
    engine = CpqEngine()
    result = engine.apply_answer(_duration_attr(), "Set SmartProgramming to 1yr")
    assert result == ("1 YEAR", "1 Year")


def test_bare_answer_yrs_abbreviation_matches_real_option():
    engine = CpqEngine()
    result = engine.apply_answer(_duration_attr(), "2yrs")
    assert result == ("2 YEAR", "2 Year")


def test_already_correct_phrasing_still_matches():
    """Confirms the normalization is additive -- the pre-existing exact
    match path is untouched."""
    engine = CpqEngine()
    result = engine.apply_answer(_duration_attr(), "2 Year")
    assert result == ("2 YEAR", "2 Year")


def test_numeric_index_selection_unaffected_by_normalization():
    """A bare digit ("2") must still be treated as a 1-based menu index,
    not accidentally touched by the yrs/yr regex (which requires a "yr"
    suffix and would never match a bare digit anyway -- this pins that
    down as a regression guard)."""
    engine = CpqEngine()
    result = engine.apply_answer(_duration_attr(), "2")
    assert result == ("2 YEAR", "2 Year")  # index 2 -> second option


def test_unrelated_value_is_not_falsely_normalized():
    engine = CpqEngine()
    result = engine.apply_answer(_duration_attr(), "some unrelated text")
    assert result is None
