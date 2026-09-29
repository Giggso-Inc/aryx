"""CPQ_Hardcode_Audit_dev_oci_2026-09-25.md Phase 4, Group 1: three
narrow, independent bug fixes with no product decisions involved.

- T5: derive_region's region-code fallback matched as a bare substring
  ("ME" inside "NORTH AMERICA"), not a whole word.
- T4a: the menu-option noise-fragment filter matched as a bare substring
  ("test" inside "LATEST RELEASE"), silently dropping real catalog
  options.
- T4b: _is_summary_excluded's year-value check ran unconditionally,
  dropping genuine Mandatory User Input lines whose value happens to
  contain the word "year"/"years".
"""
from __future__ import annotations

from unittest.mock import MagicMock

from aryx.cpq.engine import CpqEngine
from aryx.cpq.governance_and_sibling_exclusivity.region import derive_region
from aryx.cpq.product_config.product_config_menu_build import build_menu_by_attr
from aryx.cpq.state import ConfigAttr, MenuOption
from aryx.cpq.summary_display_formatting.exclusion_filters import _is_summary_excluded


# ── T5: derive_region word-boundary fix ──────────────────────────────────

def _region_attr(*options: MenuOption) -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="modelSelectionRegion_astro",
        display_label="Region", required=False, default_value="",
        select_type="single", options=list(options),
    )


def test_derive_region_middle_east_no_longer_matches_inside_north_america():
    """Live bug: region_code "ME" (Middle East) used to match as a bare
    substring inside "NORTH AMERICA" (a-ME-rica), silently resolving a
    US/Canada session to the wrong region option."""
    attr = _region_attr(
        MenuOption(item_value="NA_CODE", display_name="North America"),
    )
    # "saudi arabia" -> region_code "ME" in _COUNTRY_TO_REGION.
    result = derive_region("saudi arabia", attr)
    assert result is None, (
        "no real Middle East option on this menu -- must not wrongly "
        "match North America via the old bare-substring check"
    )


def test_derive_region_middle_east_still_matches_a_real_middle_east_option():
    attr = _region_attr(
        MenuOption(item_value="NA_CODE", display_name="North America"),
        MenuOption(item_value="ME_CODE", display_name="ME - Middle East"),
    )
    result = derive_region("saudi arabia", attr)
    assert result == ("ME_CODE", "ME - Middle East")


def test_derive_region_word_boundary_still_matches_a_whole_word_fragment():
    """The fix must not become so strict it stops matching the real,
    still-valid case of a region code appearing as a delimited whole
    word within a longer display name."""
    attr = _region_attr(
        MenuOption(item_value="NA-1", display_name="Region: NA - North America"),
    )
    result = derive_region("canada", attr)
    assert result == ("NA-1", "Region: NA - North America")


# ── T4a: noise-item-fragment word-boundary fix ───────────────────────────

def test_noise_item_fragments_no_longer_drops_latest_release():
    """Live bug cited in the audit: 'LATEST RELEASE' was silently
    dropped by the 'test' noise fragment matching inside 'la-TEST-
    release'."""
    engine = MagicMock()
    engine._batch_fetch.return_value = {
        1: {"item_value": "LATEST", "item_text": "LATEST RELEASE", "order_number": 1},
    }
    result = build_menu_by_attr(engine, 704, {100: [1]}, [1])
    assert [o.item_value for o in result[100]] == ["LATEST"]


def test_noise_item_fragments_still_filters_a_genuine_test_option():
    engine = MagicMock()
    engine._batch_fetch.return_value = {
        1: {"item_value": "TEST", "item_text": "Test", "order_number": 1},
        2: {"item_value": "REAL", "item_text": "Real Option", "order_number": 2},
    }
    result = build_menu_by_attr(engine, 704, {100: [1, 2]}, [1, 2])
    assert [o.item_value for o in result[100]] == ["REAL"]


# ── T4b: year-value-check-inside-mandatory-gate fix ──────────────────────

def _year_attr(required: bool = True) -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="someDurationAttr_astro",
        display_label="Duration", required=required, default_value="",
        select_type="single", options=[],
    )


def test_year_value_no_longer_excluded_when_line_is_mandatory():
    engine = CpqEngine()
    excluded = _is_summary_excluded(
        engine, "someDurationAttr_astro", "Duration", "2 Years",
        _year_attr(), source="user", is_mandatory=True,
    )
    assert excluded is False, (
        "a genuine Mandatory User Input line must not be dropped just "
        "because its real value happens to contain the word 'years'"
    )


def test_year_value_still_excluded_when_line_is_not_mandatory():
    engine = CpqEngine()
    excluded = _is_summary_excluded(
        engine, "someDurationAttr_astro", "Duration", "2 Years",
        _year_attr(required=False), source="rule", is_mandatory=False,
    )
    assert excluded is True, (
        "non-mandatory year/duration-shaped values are exactly what this "
        "check still targets -- must remain excluded"
    )
