"""region_for_country() -- CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T5.

_COUNTRY_TO_REGION is keyed by lowercase country NAME, plus a few literal
name-like abbreviations ("us", "uk", "uae") that happen to also look like
codes. A real ISO alpha-2 code like "CA" or "DE" was never a key in that
map, so it silently resolved to "" instead of a region. region_for_country()
resolves a code (or a name, in any casing/punctuation) to its canonical
name via the 249-country ISO alias system country/country_alias_data.py
already provides for country validation, before falling back to the map.
"""
from __future__ import annotations

from aryx.cpq.region_and_noise_constants import region_for_country


def test_country_code_resolves_the_same_as_its_full_name():
    assert region_for_country("CA") == "NA"
    assert region_for_country("Canada") == "NA"
    assert region_for_country("DE") == "EMEA"
    assert region_for_country("Germany") == "EMEA"


def test_already_working_literal_abbreviations_are_unaffected():
    assert region_for_country("US") == "NA"
    assert region_for_country("us") == "NA"
    assert region_for_country("UK") == "EMEA"
    assert region_for_country("UAE") == "ME"


def test_case_and_whitespace_insensitive():
    assert region_for_country("  ca  ") == "NA"
    assert region_for_country("cA") == "NA"


def test_unrecognized_input_returns_empty_not_an_error():
    assert region_for_country("Not A Real Country") == ""
    assert region_for_country("") == ""


def test_custom_region_map_is_honored_over_the_module_default():
    """The optional region_map param exists so callers that patch
    aryx.cpq.engine._COUNTRY_TO_REGION in a test still see that patched
    map, not the real default."""
    custom_map = {"canada": "TEST_REGION"}
    assert region_for_country("CA", custom_map) == "TEST_REGION"
    assert region_for_country("CA", {}) == ""
