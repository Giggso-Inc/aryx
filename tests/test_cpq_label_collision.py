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
