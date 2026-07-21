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
