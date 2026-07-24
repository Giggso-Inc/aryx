"""Regression tests: duplicate display_label collisions across distinct
attrs (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 2).

BigMachines source XML genuinely reuses the same <name> across functionally
different attrs (e.g. SVX's mountType_viSoln and mountingTypeArray_viSoln
both literally named "Mounting Type"). Two things must not silently guess:
(a) the filled-summary renderer, which previously showed two identical,
indistinguishable "Mounting Type" rows; (b) detect_attr_query's options-query
path, which previously resolved a label tie to whichever attr happened to be
first in list order.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr


def _attr(entity_id, variable_name, display_label, options=None):
    return ConfigAttr(
        entity_id=entity_id, variable_name=variable_name,
        display_label=display_label, required=False, default_value="",
        options=options or [],
    )


def test_detect_label_collision_flags_a_shared_label():
    eng = CpqEngine()
    attrs = [
        _attr(1, "mountType_viSoln", "Mounting Type"),
        _attr(2, "mountingTypeArray_viSoln", "Mounting Type"),
    ]
    result = eng.detect_label_collision("what are the options for Mounting Type", attrs)
    assert result is not None
    assert {a.variable_name for a in result} == {
        "mountType_viSoln", "mountingTypeArray_viSoln",
    }


def test_detect_label_collision_none_when_label_is_unique():
    eng = CpqEngine()
    attrs = [
        _attr(1, "battery_astro", "Battery"),
        _attr(2, "carry_astro", "Carry Solution"),
    ]
    assert eng.detect_label_collision("what are the options for Battery", attrs) is None


def test_detect_label_collision_none_when_variable_name_itself_matches():
    # A variable_name mention is already unambiguous — must defer to
    # detect_attr_query's own vn_matches tier, not flag a false collision.
    eng = CpqEngine()
    attrs = [
        _attr(1, "mountType_viSoln", "Mounting Type"),
        _attr(2, "mountingTypeArray_viSoln", "Mounting Type"),
    ]
    result = eng.detect_label_collision(
        "what are the options for mountType_viSoln", attrs)
    assert result is None


def test_detect_change_request_collision_flags_a_shared_label():
    # detect_change_request's own substring-subsumption fix does nothing
    # when two candidates' labels are IDENTICAL (not one subsuming the
    # other) — this is the separate check that must catch that case.
    eng = CpqEngine()
    attrs = [
        _attr(1, "serviceType_astro", "Service Type"),
        _attr(2, "serviceTypeAdditionalDMSCoverage_astro", "Service Type"),
        _attr(3, "serviceTypeRSM_astro", "Service Type"),
    ]
    filled = {
        "serviceType_astro": "ADVANTAGE",
        "serviceTypeAdditionalDMSCoverage_astro": "PREMIER",
        "serviceTypeRSM_astro": "1 YEAR STANDARD WARRANTY",
    }
    result = eng.detect_change_request_collision(
        "change service type to Premier", attrs, filled)
    assert result is not None
    assert {a.variable_name for a in result} == {
        "serviceType_astro", "serviceTypeAdditionalDMSCoverage_astro", "serviceTypeRSM_astro",
    }


def test_detect_change_request_collision_none_without_a_change_verb():
    # Gated on change-verb/arrow presence, same as detect_change_request
    # itself — a plain mention of the label with no change intent must not
    # trigger a false collision prompt.
    eng = CpqEngine()
    attrs = [
        _attr(1, "serviceType_astro", "Service Type"),
        _attr(2, "serviceTypeAdditionalDMSCoverage_astro", "Service Type"),
    ]
    filled = {"serviceType_astro": "ADVANTAGE", "serviceTypeAdditionalDMSCoverage_astro": "PREMIER"}
    assert eng.detect_change_request_collision("Service Type is Premier", attrs, filled) is None


def test_detect_change_request_collision_none_when_label_is_unique():
    eng = CpqEngine()
    attrs = [
        _attr(1, "battery_astro", "Battery"),
        _attr(2, "carry_astro", "Carry Solution"),
    ]
    filled = {"battery_astro": "STANDARD", "carry_astro": "STANDARD"}
    assert eng.detect_change_request_collision("change Battery to Extended", attrs, filled) is None


def test_detect_change_request_collision_ignores_unfilled_attrs():
    # An attr not yet in filled/filled_multi can't be the target of a
    # "change X" request in the first place.
    eng = CpqEngine()
    attrs = [
        _attr(1, "serviceType_astro", "Service Type"),
        _attr(2, "serviceTypeAdditionalDMSCoverage_astro", "Service Type"),
    ]
    filled = {"serviceType_astro": "ADVANTAGE"}  # only one of the two is filled
    assert eng.detect_change_request_collision(
        "change service type to Premier", attrs, filled) is None


def test_detect_change_request_collision_does_not_break_sibling_substring_case():
    # Genuine subsumption (one label a literal substring of another) is
    # detect_change_request's OWN separate _superseded mechanism's job —
    # this collision check must stay silent for that shape (different
    # labels entirely), not double-fire.
    eng = CpqEngine()
    attrs = [
        _attr(1, "accecsssoriesQuantityArray_viSoln", "Quantity"),
        _attr(2, "mountingTypeLockingMolleMountQuantity_viSoln",
              "mounting type Locking Molle Mount Quantity"),
    ]
    filled = {
        "accecsssoriesQuantityArray_viSoln": "1",
        "mountingTypeLockingMolleMountQuantity_viSoln": "1",
    }
    assert eng.detect_change_request_collision(
        "Change the mounting type Locking Molle Mount Quantity to 10", attrs, filled) is None


def test_detect_change_request_collision_finds_specific_match_with_dropped_prefix():
    # Real SVX transcript (confirmed live): "change the Shirt Magnetic
    # Mount Quantity to 99" — the specific attr's real label is "mounting
    # type Shirt Magnetic Mount Quantity", but the user's phrasing drops
    # the generic "mounting type" prefix entirely. A strict substring
    # check never sees the specific attr as a candidate at all (only the
    # 3 unrelated generic "Quantity" attrs), wrongly reporting a 3-way
    # collision — must use the same fuzzy _label_mentioned matcher
    # detect_change_request's own resolver uses, so the specific match is
    # found and supersedes the generic collision.
    eng = CpqEngine()
    attrs = [
        _attr(1, "accecsssoriesQuantityArray_viSoln", "Quantity"),
        _attr(2, "mountingTypeArrayqty_viSoln", "Quantity"),
        _attr(3, "Accessories2Quantity_viSoln", "Quantity"),
        _attr(4, "mountingTypeShirtMagneticMountQuantity_viSoln",
              "mounting type Shirt Magnetic Mount Quantity"),
    ]
    filled = {
        "accecsssoriesQuantityArray_viSoln": "",
        "mountingTypeArrayqty_viSoln": "",
        "Accessories2Quantity_viSoln": "",
        "mountingTypeShirtMagneticMountQuantity_viSoln": "88",
    }
    assert eng.detect_change_request_collision(
        "change the Shirt Magnetic Mount Quantity to 99", attrs, filled) is None


def test_detect_change_request_collision_superseded_by_a_more_specific_match():
    # Real SVX transcript (confirmed live): "change mounting type Shirt
    # Magnetic Mount Quantity to 88" false-positived a "Mounting Type"
    # collision between mountType_viSoln/mountingTypeArray_viSoln, purely
    # because the message's own text happens to start with "mounting type"
    # — even though the actual target (the quantity attr) is unambiguous
    # on its own and fully accounts for that substring.
    eng = CpqEngine()
    attrs = [
        _attr(1, "mountType_viSoln", "Mounting Type"),
        _attr(2, "mountingTypeArray_viSoln", "Mounting Type"),
        _attr(3, "mountingTypeShirtMagneticMountQuantity_viSoln",
              "mounting type Shirt Magnetic Mount Quantity"),
    ]
    filled = {
        "mountType_viSoln": "Swivel Clip and Adjustable Lanyard",
        "mountingTypeArray_viSoln": "Shirt Magnetic Mount, Jacket Magnetic Mount",
        "mountingTypeShirtMagneticMountQuantity_viSoln": "44",
    }
    result = eng.detect_change_request_collision(
        "change mounting type Shirt Magnetic Mount Quantity to 88", attrs, filled)
    assert result is None


def test_filled_summary_disambiguates_colliding_labels_with_variable_name():
    eng = CpqEngine()
    attrs = [
        _attr(1, "mountType_viSoln", "Mounting Type"),
        _attr(2, "mountingTypeArray_viSoln", "Mounting Type"),
        _attr(3, "battery_astro", "Battery"),
    ]
    display_filled = {
        "mountType_viSoln": "Swivel Clip and Adjustable Lanyard",
        "mountingTypeArray_viSoln": "Shirt Magnetic Mount, Jacket Magnetic Mount",
        "battery_astro": "STANDARD",
    }
    triples = eng._filled_summary_triples(display_filled, attrs)
    labels = {var: label for var, label, _val in triples}
    assert labels["mountType_viSoln"] == "Mounting Type (mountType_viSoln)"
    assert labels["mountingTypeArray_viSoln"] == "Mounting Type (mountingTypeArray_viSoln)"
    assert labels["battery_astro"] == "Battery"  # unique label, untouched
