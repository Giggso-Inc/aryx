"""Regression coverage for detect_change_requests_multi() — true
multi-attribute change support in a single message (product decision:
cap at 3 attrs per message, partial-apply + report failures on the
ask_api.py side).

detect_change_request's underlying scan (`_change_request_matches`) was
refactored into a generator so both the single-match function and this
new multi-match function share the exact same matching logic — no
duplicated grammar to drift out of sync.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr


def _attr(entity_id, vn, label):
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=label,
        required=False, default_value="", options=[],
    )


def test_multi_change_finds_both_sibling_quantities_with_their_own_numbers():
    eng = CpqEngine()
    attrs = [
        _attr(1, "mountingTypeShirtMagneticMountQuantity_viSoln",
              "mounting type Shirt Magnetic Mount Quantity"),
        _attr(2, "mountingTypeJacketMagneticMountQuantity_viSoln",
              "mounting type Jacket Magnetic Mount Quantity"),
    ]
    filled = {
        "mountingTypeShirtMagneticMountQuantity_viSoln": "15",
        "mountingTypeJacketMagneticMountQuantity_viSoln": "15",
    }
    matches = eng.detect_change_requests_multi(
        "change the Shirt Magnetic Mount Quantity to 25 and the Jacket Magnetic Mount Quantity to 30",
        attrs, filled)
    assert [(a.variable_name, v) for a, v in matches] == [
        ("mountingTypeShirtMagneticMountQuantity_viSoln", "25"),
        ("mountingTypeJacketMagneticMountQuantity_viSoln", "30"),
    ]


def test_single_change_request_still_returns_first_match_only():
    # detect_change_request (singular) must be completely unaffected by
    # the generator refactor — same first-match contract as before.
    eng = CpqEngine()
    attrs = [
        _attr(1, "mountingTypeShirtMagneticMountQuantity_viSoln",
              "mounting type Shirt Magnetic Mount Quantity"),
        _attr(2, "mountingTypeJacketMagneticMountQuantity_viSoln",
              "mounting type Jacket Magnetic Mount Quantity"),
    ]
    filled = {
        "mountingTypeShirtMagneticMountQuantity_viSoln": "15",
        "mountingTypeJacketMagneticMountQuantity_viSoln": "15",
    }
    result = eng.detect_change_request(
        "change the Shirt Magnetic Mount Quantity to 25 and the Jacket Magnetic Mount Quantity to 30",
        attrs, filled)
    assert result is not None
    attr, value = result
    assert attr.variable_name == "mountingTypeShirtMagneticMountQuantity_viSoln"
    assert value == "25"


def test_multi_change_returns_empty_list_when_nothing_matches():
    eng = CpqEngine()
    attrs = [_attr(1, "batteryType_astro", "Battery Type")]
    filled = {"batteryType_astro": "Standard"}
    assert eng.detect_change_requests_multi("what's the weather like", attrs, filled) == []


def test_multi_change_is_capped_at_three():
    eng = CpqEngine()
    attrs = [
        _attr(1, "aQuantity_viSoln", "Widget A Quantity"),
        _attr(2, "bQuantity_viSoln", "Widget B Quantity"),
        _attr(3, "cQuantity_viSoln", "Widget C Quantity"),
        _attr(4, "dQuantity_viSoln", "Widget D Quantity"),
    ]
    filled = {
        "aQuantity_viSoln": "1", "bQuantity_viSoln": "1",
        "cQuantity_viSoln": "1", "dQuantity_viSoln": "1",
    }
    q = (
        "change Widget A Quantity to 2 and Widget B Quantity to 3 "
        "and Widget C Quantity to 4 and Widget D Quantity to 5"
    )
    matches = eng.detect_change_requests_multi(q, attrs, filled)
    assert len(matches) == 3
