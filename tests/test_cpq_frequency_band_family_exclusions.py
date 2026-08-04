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
