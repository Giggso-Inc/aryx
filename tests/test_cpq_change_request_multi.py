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


def _attr(entity_id, vn, label, *, options=None, select_type="single"):
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=label,
        required=False, default_value="", options=options or [],
        select_type=select_type,
    )


def _opt(*values):
    from aryx.cpq.state import MenuOption
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


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


# docs/config_consistency_issues_2026-07-30.md issue 4 follow-up — a
# multi-select the customer never touched still gets a `[]` entry in
# filled_multi from auto_fill/hiding-rule evaluation (confirmed live:
# nearly every multi-select attr in a real catalog carries this). The old
# `vn in filled_multi` check treated dict KEY PRESENCE as "already
# filled", wrongly making an untouched multi-select an eligible implicit
# change-request target the moment its option list happens to contain the
# customer's bare value — even while a genuinely pending, unrelated
# single-select attribute was correctly waiting for that exact reply.

def test_untouched_empty_multi_select_is_not_an_eligible_candidate():
    """Real incident: with Frequency Bands (single-select) as the actual,
    correctly-pending attribute, a bare 'VHF' reply still matched an
    untouched Frequency Band Msl multi-select (filled_multi[vn] == [])
    here, because 'VHF' is also one of ITS real option values — writing
    the reply into the wrong attribute entirely and leaving the real
    pending one stale (bom_gate then re-detects it as invalid every
    confirm, looping forever).

    detect_change_request itself has no special-case value-only matching
    for a single-select attr with no label mention — Bands correctly
    returns no match here either way (it needs STEP 5's dedicated
    pending-answer lock, tested at the ask_api layer, not this generic
    scan). The fix this test pins is narrower and just as critical: the
    untouched Msl multi-select must ALSO return no match, instead of
    incorrectly winning by default and consuming the reply before STEP 5
    ever sees it.
    """
    eng = CpqEngine()
    bands = _attr(1, "modelSelectionFrequencyBands_astro", "Frequency Bands",
                   options=_opt("700/800 MHZ", "VHF", "UHF"))
    msl = _attr(2, "modelSelectionFrequencyBandMsl_astro", "Frequency Band",
                options=_opt("700/800 MHZ", "VHF", "UHF"), select_type="multi")
    attrs = [bands, msl]
    filled = {"modelSelectionFrequencyBands_astro": "700/800 MHZ"}
    # Untouched — engine seeded an empty list, customer never selected anything.
    filled_multi = {"modelSelectionFrequencyBandMsl_astro": []}

    result = eng.detect_change_request("VHF", attrs, filled, filled_multi=filled_multi)

    assert result is None, (
        "an untouched multi-select (empty [] entry, never a real "
        "selection) must never be treated as an eligible change-request "
        "target just because its option list happens to contain the "
        "customer's bare value — that's the exact wrong-attribute-write "
        "bug this test pins"
    )


def test_multi_select_with_a_real_selection_is_still_an_eligible_candidate():
    """The fix must not break the legitimate case — a multi-select the
    customer actually populated stays a valid change-request target."""
    eng = CpqEngine()
    msl = _attr(1, "modelSelectionFrequencyBandMsl_astro", "Frequency Band",
                options=_opt("700/800 MHZ", "VHF", "UHF"), select_type="multi")
    attrs = [msl]
    filled_multi = {"modelSelectionFrequencyBandMsl_astro": ["700/800 MHZ"]}

    result = eng.detect_change_request(
        "change Frequency Band to VHF", attrs, {}, filled_multi=filled_multi)

    assert result is not None
    attr, _value = result
    assert attr.variable_name == "modelSelectionFrequencyBandMsl_astro"
