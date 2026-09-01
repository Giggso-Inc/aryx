"""apply_constraint_rules must tolerate a catalog rule's own allowed-value
list carrying different letter-casing than the attribute's real menu
item_value.

Real incident (docs/config_consistency_issues_2026-07-30.md): the raw
catalog's own declarative constraint rule "Constrain for APXNEXTSINGLE &
APXNEXTXNSINGLE" lists "700/800 MHz" as an allowed value for Frequency
Bands, while every real menu item for that attribute is authored
"700/800 MHZ" (uppercase Z) — a genuine source-catalog authoring
inconsistency, not a bug in this parsing. Left uncorrected, the
BOM-gate's stale-constraint check (bom_gate.recheck_constraints, a plain
`current not in allowed` comparison) treated a brand-new, completely
default APX NEXT Single Band order's own default Frequency Bands value
as invalid on the very first confirm, every single time — the value was
never actually wrong, it just didn't case-exact-match the rule's own
typo.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, ConstraintRule, MenuOption


def _attr(entity_id, vn, label, *, options):
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=label,
        required=False, default_value="", options=options,
    )


def _opt(*values):
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


_BANDS = _attr(
    1, "modelSelectionFrequencyBands_astro", "Frequency Bands",
    options=_opt("700/800 MHZ", "VHF", "UHF"),
)
_PRODUCT = _attr(2, "productSelectionProduct_all", "Product", options=_opt("APX NEXT SINGLE BAND"))
_FILLED = {
    "productSelectionProduct_all": "APX NEXT SINGLE BAND",
    "modelSelectionFrequencyBands_astro": "700/800 MHZ",
}


def _rule(name, allowed_values):
    return ConstraintRule(
        rule_name=name, condition_attr_id=_PRODUCT.entity_id,
        condition_value="APX NEXT SINGLE BAND",
        target_attr_id=_BANDS.entity_id, allowed_values=allowed_values,
    )


def test_declarative_rule_with_mismatched_casing_still_allows_the_real_value():
    # Real catalog data: the rule's own allowed-list carries "700/800 MHz"
    # (lowercase z) — different casing from the attribute's real item_value
    # "700/800 MHZ".
    rule = _rule("Constrain for APXNEXTSINGLE & APXNEXTXNSINGLE",
                  ["UHF", "VHF", "700/800 MHz"])
    eng = CpqEngine()

    constrained = eng.apply_constraint_rules([_BANDS, _PRODUCT], [rule], _FILLED)

    allowed = constrained.get(_BANDS.entity_id)
    assert allowed is not None
    assert "700/800 MHZ" in allowed, (
        "a rule's own allowed-value entry with different letter-casing "
        "than the real catalog item_value must still match it — this is "
        "the exact false-positive that made a default, unmodified order "
        "fail its own BOM-gate stale-constraint check on the first confirm"
    )
    # Normalized to the REAL catalog casing, not left as the rule's typo —
    # matters for correctly-cased reprompt display too.
    assert "700/800 MHz" not in allowed


def test_correctly_cased_rule_is_unaffected():
    """The fix must not change behavior for the common case where the
    rule's own casing already matches the catalog."""
    rule = _rule("Some other rule", ["VHF", "UHF"])
    eng = CpqEngine()

    constrained = eng.apply_constraint_rules([_BANDS, _PRODUCT], [rule], _FILLED)

    assert constrained.get(_BANDS.entity_id) == ["VHF", "UHF"]


def test_intersection_across_multiple_rules_still_works_with_casing_fix():
    """Two active rules for the same target must still intersect (AND
    semantics) after normalization, not just pass through unioned."""
    rule_a = _rule("Rule A", ["700/800 MHz", "VHF", "UHF"])
    rule_b = _rule("Rule B", ["VHF"])
    eng = CpqEngine()

    constrained = eng.apply_constraint_rules([_BANDS, _PRODUCT], [rule_a, rule_b], _FILLED)

    assert constrained.get(_BANDS.entity_id) == ["VHF"]


def test_a_value_not_in_the_real_catalog_options_passes_through_unchanged():
    """Normalization only rewrites case for a REAL catalog option match —
    it must never invent or silently accept a genuinely unknown value."""
    rule = _rule("Weird rule", ["totally-unknown-value"])
    eng = CpqEngine()

    constrained = eng.apply_constraint_rules([_BANDS, _PRODUCT], [rule], _FILLED)

    assert constrained.get(_BANDS.entity_id) == ["totally-unknown-value"]
