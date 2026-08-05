"""Regression tests: Issue 5 (docs/config_consistency_issues_2026-07-30.md).

Generic, catalog-agnostic detector: two attrs sharing the same real-world
concept (near-identical display label, e.g. "Frequency Bands" vs
"Frequency Band"), one select_type=="multi" and the other not, can both
end up filled in the same turn when no catalog hiding rule actually
excludes either one for the current product (confirmed live on the APX
Next catalog — the active hiding rule for the single-select sibling
omits some product values entirely). No product/catalog/attribute names
are hardcoded — detection is purely by label similarity, select_type, and
provenance (only acts when the single-select value came from an
unconditional default_value, never a real hint/user/rule answer).
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr


def _attr(entity_id, variable_name, display_label, select_type="single"):
    return ConfigAttr(
        entity_id=entity_id, variable_name=variable_name,
        display_label=display_label, required=False, default_value="",
        options=[], select_type=select_type,
    )


def test_strips_weakly_sourced_single_sibling_and_asks_for_multi_sibling():
    eng = CpqEngine()
    attrs = [
        _attr(1, "modelSelectionFrequencyBands_astro", "Frequency Bands", "single"),
        _attr(2, "modelSelectionFrequencyBandMsl_astro", "Frequency Band", "multi"),
    ]
    filled = {"modelSelectionFrequencyBands_astro": "700/800 MHZ"}
    filled_multi = {}
    filled_source = {"modelSelectionFrequencyBands_astro": "default"}

    to_strip, to_ask = eng.exclusive_sibling_family_exclusions(
        attrs, filled, filled_multi, filled_source,
    )

    assert to_strip == {"modelSelectionFrequencyBands_astro"}
    assert [a.variable_name for a in to_ask] == ["modelSelectionFrequencyBandMsl_astro"]


def test_strips_a_rule_sourced_single_sibling_too():
    """Confirmed live: this catalog's single-select sibling is actually
    populated by a shared-input RECOMMENDATION rule (source "rule"), not
    a bare XML default_value — the check must catch this too, not just
    literal source=="default"."""
    eng = CpqEngine()
    attrs = [
        _attr(1, "modelSelectionFrequencyBands_astro", "Frequency Bands", "single"),
        _attr(2, "modelSelectionFrequencyBandMsl_astro", "Frequency Band", "multi"),
    ]
    filled = {"modelSelectionFrequencyBands_astro": "700/800 MHZ"}
    filled_source = {"modelSelectionFrequencyBands_astro": "rule"}

    to_strip, to_ask = eng.exclusive_sibling_family_exclusions(
        attrs, filled, {}, filled_source,
    )
    assert to_strip == {"modelSelectionFrequencyBands_astro"}
    assert [a.variable_name for a in to_ask] == ["modelSelectionFrequencyBandMsl_astro"]


def test_does_not_strip_a_real_user_answered_value():
    """A customer-confirmed value must never be second-guessed — only the
    weakest provenance (unconditional XML default) triggers this."""
    eng = CpqEngine()
    attrs = [
        _attr(1, "modelSelectionFrequencyBands_astro", "Frequency Bands", "single"),
        _attr(2, "modelSelectionFrequencyBandMsl_astro", "Frequency Band", "multi"),
    ]
    filled = {"modelSelectionFrequencyBands_astro": "700/800 MHZ"}
    filled_source = {"modelSelectionFrequencyBands_astro": "user"}

    to_strip, to_ask = eng.exclusive_sibling_family_exclusions(
        attrs, filled, {}, filled_source,
    )
    assert to_strip == set()
    assert to_ask == []


def test_no_action_when_multi_sibling_already_has_a_value():
    eng = CpqEngine()
    attrs = [
        _attr(1, "modelSelectionFrequencyBands_astro", "Frequency Bands", "single"),
        _attr(2, "modelSelectionFrequencyBandMsl_astro", "Frequency Band", "multi"),
    ]
    filled = {"modelSelectionFrequencyBands_astro": "700/800 MHZ"}
    filled_multi = {"modelSelectionFrequencyBandMsl_astro": ["UHF"]}
    filled_source = {"modelSelectionFrequencyBands_astro": "default"}

    to_strip, to_ask = eng.exclusive_sibling_family_exclusions(
        attrs, filled, filled_multi, filled_source,
    )
    assert to_strip == set()
    assert to_ask == []


def test_wireless_carrier_pair_is_an_explicit_named_exception():
    """wirelessCarrier_astro/carrierSelectionMultiSelect_astro do NOT share
    a label stem ("Wireless Carrier" vs "Carrier Selection") — the generic
    detector alone could never pair them. Live-confirmed this exact pair
    exhibits the identical wrong-sibling bug as the label-matched
    Frequency Band pair (a real, valid-for-both-attrs value like
    "ATT/FIRSTNET" lands in the single-select sibling while the multi-
    select governing attribute stays empty), so it's handled via an
    explicit, disclosed named exception (_KNOWN_SIBLING_PAIRS) rather than
    silently widening the label heuristic to something it can't detect."""
    eng = CpqEngine()
    attrs = [
        _attr(1, "wirelessCarrier_astro", "Wireless Carrier", "single"),
        _attr(2, "carrierSelectionMultiSelect_astro", "Carrier Selection", "multi"),
    ]
    filled = {"wirelessCarrier_astro": "ATT/FIRSTNET"}
    filled_source = {"wirelessCarrier_astro": "rule"}

    to_strip, to_ask = eng.exclusive_sibling_family_exclusions(
        attrs, filled, {}, filled_source,
    )
    assert to_strip == {"wirelessCarrier_astro"}
    assert [a.variable_name for a in to_ask] == ["carrierSelectionMultiSelect_astro"]


def test_unrelated_dissimilar_labels_are_never_paired():
    """A genuinely unrelated single/multi pair with dissimilar labels and
    NOT in the explicit exception list must never be guessed as siblings."""
    eng = CpqEngine()
    attrs = [
        _attr(1, "someUnrelatedSingle_astro", "Battery Type", "single"),
        _attr(2, "someUnrelatedMulti_astro", "Accessory Options", "multi"),
    ]
    filled = {"someUnrelatedSingle_astro": "STANDARD"}
    filled_source = {"someUnrelatedSingle_astro": "default"}

    to_strip, to_ask = eng.exclusive_sibling_family_exclusions(
        attrs, filled, {}, filled_source,
    )
    assert to_strip == set()
    assert to_ask == []


def test_four_way_label_collision_not_visible_this_turn_is_never_paired():
    """docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_PLAN_2026_08_05.md
    follow-up, live incident: a real catalog reuses the identical display
    label "Service Type" across 4 semantically unrelated attributes.
    Passing only the 2 currently-VISIBLE ones (as `attrs`) without
    `all_attrs` would satisfy the size-2 check and wrongly pair them --
    passing the full 4-attr catalog as `all_attrs` must correctly see the
    real group size and refuse to pair any of them, exactly like any
    other 3+-way label collision."""
    eng = CpqEngine()
    visible = [
        _attr(2, "relatedServicesType_astro", "Service Type", "multi"),
        _attr(3, "serviceTypeAdditionalDMSCoverage_astro", "Service Type", "single"),
    ]
    all_attrs = visible + [
        _attr(1, "serviceType_astro", "Service Type", "single"),
        _attr(4, "serviceTypeRSM_astro", "Service Type", "single"),
    ]
    filled = {"serviceTypeAdditionalDMSCoverage_astro": "PREMIER"}
    filled_source = {"serviceTypeAdditionalDMSCoverage_astro": "default"}

    to_strip, to_ask = eng.exclusive_sibling_family_exclusions(
        visible, filled, {}, filled_source, all_attrs=all_attrs,
    )
    assert to_strip == set()
    assert to_ask == []


def test_four_way_label_collision_without_all_attrs_reproduces_the_bug():
    """Sanity check proving the bug is real and the fix is the `all_attrs`
    parameter specifically: the SAME 2-attr-visible scenario above, without
    passing `all_attrs` at all (old call signature), DOES incorrectly pair
    them -- confirms this is a genuine regression fix, not a no-op."""
    eng = CpqEngine()
    visible = [
        _attr(2, "relatedServicesType_astro", "Service Type", "multi"),
        _attr(3, "serviceTypeAdditionalDMSCoverage_astro", "Service Type", "single"),
    ]
    filled = {"serviceTypeAdditionalDMSCoverage_astro": "PREMIER"}
    filled_source = {"serviceTypeAdditionalDMSCoverage_astro": "default"}

    to_strip, to_ask = eng.exclusive_sibling_family_exclusions(
        visible, filled, {}, filled_source,
    )
    assert to_strip == {"serviceTypeAdditionalDMSCoverage_astro"}
    assert [a.variable_name for a in to_ask] == ["relatedServicesType_astro"]


def test_hidden_multi_sibling_is_never_pulled_back_from_all_attrs():
    """Live regression from the all_attrs fix itself: modelSelectionFrequency
    BandMsl_astro is correctly hidden for "APX NEXT All Band" by a real,
    named hiding rule ("Hide Frequency Band Model Selection Attribute for
    APX NEXT All Band model") and correctly excluded from the visible
    `attrs` this turn -- but its single-select sibling still got a weak
    default. `all_attrs` (needed for the 4-way-collision fix above) must
    NOT let a hidden sibling be pulled back in as the "real" answer to
    defer to: neither stripping the single's weak value nor asking the
    hidden multi-select at all. A customer answering the (correctly
    re-asked, per the OLD bug) multi-select question then had their real
    answer silently discarded every subsequent turn -- since the multi-
    select is hidden, evaluate_rules_loop's own hidden-attr cleanup pops
    it right back out, and the pairing logic kept re-adding it to
    `pending`, producing an infinite repeat of the same question."""
    eng = CpqEngine()
    visible = [
        _attr(1, "modelSelectionFrequencyBands_astro", "Frequency Bands", "single"),
        # modelSelectionFrequencyBandMsl_astro deliberately NOT in `visible`
        # -- this turn's hiding rule excluded it.
    ]
    all_attrs = visible + [
        _attr(2, "modelSelectionFrequencyBandMsl_astro", "Frequency Band", "multi"),
    ]
    filled = {"modelSelectionFrequencyBands_astro": "700/800 MHZ"}
    filled_source = {"modelSelectionFrequencyBands_astro": "default"}

    to_strip, to_ask = eng.exclusive_sibling_family_exclusions(
        visible, filled, {}, filled_source, all_attrs=all_attrs,
    )
    assert to_strip == set(), (
        "no more-specific (visible) answer to defer to -- the weak "
        "single-select default must be left alone, not stripped for nothing"
    )
    assert to_ask == []

    pending = eng.enforce_exclusive_sibling_families(
        visible, filled, {}, filled_source, {}, [], all_attrs=all_attrs,
    )
    assert pending == [], "a hidden sibling must never be resurrected into pending"
    assert filled.get("modelSelectionFrequencyBands_astro") == "700/800 MHZ"


def test_enforce_mutates_filled_and_appends_to_pending():
    eng = CpqEngine()
    attrs = [
        _attr(1, "modelSelectionFrequencyBands_astro", "Frequency Bands", "single"),
        _attr(2, "modelSelectionFrequencyBandMsl_astro", "Frequency Band", "multi"),
    ]
    filled = {"modelSelectionFrequencyBands_astro": "700/800 MHZ"}
    display_filled = {"modelSelectionFrequencyBands_astro": "700/800 MHz"}
    filled_source = {"modelSelectionFrequencyBands_astro": "default"}
    filled_multi = {}
    pending = []

    pending = eng.enforce_exclusive_sibling_families(
        attrs, filled, filled_multi, filled_source, display_filled, pending,
    )

    assert "modelSelectionFrequencyBands_astro" not in filled
    assert "modelSelectionFrequencyBands_astro" not in display_filled
    assert "modelSelectionFrequencyBands_astro" not in filled_source
    assert [a.variable_name for a in pending] == ["modelSelectionFrequencyBandMsl_astro"]


def test_enforce_still_asks_when_multi_sibling_has_an_empty_placeholder():
    """Live-confirmed bug: auto_fill's own multi-select branch can leave an
    EMPTY LIST placeholder key in filled_multi ("leave unselected" — see
    auto_fill's docstring) tagged source "default". A membership check
    (`vn not in filled_multi`) treats that placeholder KEY as "already
    resolved" and silently skips asking — the config wrongly completes
    with the real governing attribute left empty. Must check truthiness
    of the value, not mere key presence."""
    eng = CpqEngine()
    attrs = [
        _attr(1, "modelSelectionFrequencyBands_astro", "Frequency Bands", "single"),
        _attr(2, "modelSelectionFrequencyBandMsl_astro", "Frequency Band", "multi"),
    ]
    filled = {"modelSelectionFrequencyBands_astro": "700/800 MHZ"}
    filled_source = {"modelSelectionFrequencyBands_astro": "default"}
    filled_multi = {"modelSelectionFrequencyBandMsl_astro": []}
    pending = []

    pending = eng.enforce_exclusive_sibling_families(
        attrs, filled, filled_multi, filled_source, {}, pending,
    )
    assert [a.variable_name for a in pending] == ["modelSelectionFrequencyBandMsl_astro"]


def test_enforce_does_not_duplicate_an_already_pending_attr():
    eng = CpqEngine()
    msl = _attr(2, "modelSelectionFrequencyBandMsl_astro", "Frequency Band", "multi")
    attrs = [
        _attr(1, "modelSelectionFrequencyBands_astro", "Frequency Bands", "single"),
        msl,
    ]
    filled = {"modelSelectionFrequencyBands_astro": "700/800 MHZ"}
    filled_source = {"modelSelectionFrequencyBands_astro": "default"}
    pending = [msl]

    pending = eng.enforce_exclusive_sibling_families(
        attrs, filled, {}, filled_source, {}, pending,
    )
    assert len(pending) == 1
