"""docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_PLAN_2026_08_05.md

auto_fill's multi-select branch treated "here is the current menu of
constraint-allowed choices" as "auto-select every one of them", for any
active constraint however many options it left standing. Real incident:
"Constrain Additional feature Type" (condition: any product selected --
true for virtually every order) narrows a real attribute to 9 of 11
options; that 9-item list is a MENU definition, not a recommendation to
select all 9. auto_fill force-selected all 9 (including "ICE KIT"), which
silently triggered an unrelated constraint that collapsed a real question
(Package Type) to zero valid options.

Fix 1: require len(valid_opts) == 1 for the multi-select auto-select-via-
constraint path, exactly mirroring the single-select safeguard directly
above it in the same function.

Fix 2 (second finding, same investigation): the fall-through path for an
attr Fix 1 now declines to auto-select landed in the SEPARATE, pre-existing
"genuinely unconstrained optional multi-select -> auto-assign empty"
branch, which never actually checked whether a constraint was active --
only select_type/required/grid-selector. That silently turned "ambiguous,
still-unresolved" into "confirmed nothing selected", written to
filled_multi as []. _filled_by_rule_id treats an explicit [] as a real,
known-empty value ("~".join([]) == "") -- so any sibling rule keyed on
"does NOT contain value X" (operator "8", disjoint-from) sees that "" and
fires as if the customer had confirmed nothing, restricting some other
attr's allowed values based on a fact nobody actually confirmed. Live:
this collapsed Package Type via a *different* rule than Fix 1's ICE-KIT
one ("Hide Single Pack Calmshell when...is not selected as feature type"),
same empty-question symptom. Fix: the empty-assign branch now also
requires the attr to have NO active constraint at all (not merely "not
exactly one remaining option") -- an attr a constraint narrowed to several
options is a real unresolved choice and must be asked, not defaulted.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, ConstraintRule, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def test_multiselect_with_several_constrained_options_is_not_auto_selected():
    """Replays the real "additionalSystemEnhancementFeatureType_astro"
    shape: a near-universal constraint narrows 11 real options down to 9
    -- must NOT auto-select all 9; must fall through to pending instead."""
    attr = ConfigAttr(
        entity_id=1, variable_name="additionalSystemEnhancementFeatureType_astro",
        display_label="Additional System Enhancement Feature Type",
        required=False, default_value="", select_type="multi",
        options=_menu(
            "DISABLE CLOUD SERVICES", "DELETE NARROWBANDING-WAIVER REQUIRED",
            "ICE KIT", "OPTIONAL EMERGENCY TONE", "SEQUENTIAL SERIAL NUMBER",
            "FRONT PANEL PROGRAMMING & CLONING", "FRONT PANEL PROGRAMMING & CLONING FED",
            "PROGRAMMING OVER P25", "PSU CONV SCAN", "WEB BROWSER ENABLEMENT",
        ),
    )
    constrained_opts = {1: [
        "DISABLE CLOUD SERVICES", "ICE KIT", "OPTIONAL EMERGENCY TONE",
        "FRONT PANEL PROGRAMMING & CLONING", "FRONT PANEL PROGRAMMING & CLONING FED",
        "PROGRAMMING OVER P25", "PSU CONV SCAN", "WEB BROWSER ENABLEMENT",
    ]}  # 8 of 10 remain -- multiple options, not a deterministic single choice

    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=constrained_opts,
        governed_ids={1}, rule_governed_ids={1}, already_filled_multi=multi,
    )

    # Must NOT fall into the separate "optional multi-select, nothing to
    # justify a subset -> explicit empty selection" fallback either
    # (engine.py ~line 5430) -- that fallback is for attrs with NO active
    # constraint at all; this attr DOES have one (just an ambiguous one),
    # so a false "confirmed empty" would feed a wrong-but-certain answer
    # to any sibling rule keyed on "does this attr contain/not contain
    # value X" (docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_PLAN_
    # 2026_08_05.md's second finding). Must be left absent -> asked.
    assert "additionalSystemEnhancementFeatureType_astro" not in multi, (
        "narrowing to SEVERAL remaining options is a real, unresolved "
        "choice -- must never be auto-selected in full, same guessing "
        "risk D2 exists to prevent"
    )


def test_multiselect_constrained_to_exactly_one_option_is_still_auto_selected():
    """Regression: narrowing to exactly ONE remaining option is exactly as
    unambiguous for multi-select as it already is for single-select --
    must remain auto-filled, unchanged from before this fix."""
    attr = ConfigAttr(
        entity_id=2, variable_name="packageTypeBundles_astro", display_label="Software Bundles",
        required=False, default_value="", select_type="multi",
        options=_menu("CORE BUNDLE", "SECURITY BUNDLE", "TACTICAL BUNDLE"),
    )
    constrained_opts = {2: ["CORE BUNDLE"]}

    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=constrained_opts,
        governed_ids={2}, rule_governed_ids={2}, already_filled_multi=multi,
    )

    assert multi.get("packageTypeBundles_astro") == ["CORE BUNDLE"]


def test_multiselect_with_no_active_constraint_stays_unselected():
    """Regression: no constraint at all -- unaffected by this fix, still
    left unselected (unchanged pre-existing behavior)."""
    attr = ConfigAttr(
        entity_id=3, variable_name="carrierSelectionMultiSelect_astro", display_label="Carrier Selection",
        required=False, default_value="", select_type="multi",
        options=_menu("ATT/FIRSTNET", "VERIZON", "T MOBILE"),
    )
    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=None,
        governed_ids={3}, rule_governed_ids={3}, already_filled_multi=multi,
    )
    # Same pre-existing "optional multi-select, nothing to justify a
    # subset -> explicit empty selection" fallback as above.
    assert multi.get("carrierSelectionMultiSelect_astro") == []


def test_multiselect_trivial_single_real_option_total_is_auto_selected():
    """Regression: an attribute with only ONE real option in the whole
    catalog (constrained set == the full option set) is still safely
    auto-filled -- there's no ambiguity when there's only one thing to
    ever pick."""
    attr = ConfigAttr(
        entity_id=4, variable_name="provisioningAssistance_astro", display_label="Provisioning Assistance",
        required=False, default_value="", select_type="multi",
        options=_menu("YES"),
    )
    constrained_opts = {4: ["YES"]}
    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=constrained_opts,
        governed_ids={4}, rule_governed_ids={4}, already_filled_multi=multi,
    )
    assert multi.get("provisioningAssistance_astro") == ["YES"]


def test_ambiguous_multiselect_left_unresolved_does_not_falsely_satisfy_sibling_disjoint_from_rule():
    """End-to-end replay of the real "Package Type" symptom's actual
    mechanism (docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_PLAN_2026_08_05.md
    second finding): a sibling ConstraintRule's "does NOT contain ICE KIT"
    (operator "8", disjoint-from) condition must NOT be satisfied by an
    ambiguous multi-select nobody has actually resolved yet -- it must only
    fire once the attribute is genuinely confirmed empty (or confirmed to
    not contain ICE KIT), not merely absent/unfilled."""
    feature_attr = ConfigAttr(
        entity_id=10, variable_name="additionalSystemEnhancementFeatureType_astro",
        display_label="Additional System Enhancement Feature Type",
        required=False, default_value="", select_type="multi",
        options=_menu(
            "DISABLE CLOUD SERVICES", "ICE KIT", "OPTIONAL EMERGENCY TONE",
            "FRONT PANEL PROGRAMMING & CLONING", "FRONT PANEL PROGRAMMING & CLONING FED",
            "PROGRAMMING OVER P25", "PSU CONV SCAN", "WEB BROWSER ENABLEMENT",
            "SEQUENTIAL SERIAL NUMBER", "DELETE NARROWBANDING-WAIVER REQUIRED",
        ),
    )
    package_type_attr = ConfigAttr(
        entity_id=11, variable_name="packingPackageType_astro", display_label="Package Type",
        required=False, default_value="", select_type="single",
        options=_menu("BULK XE", "SINGLE XE", "SINGLE PACK CLAMSHELL"),
    )
    product_attr = ConfigAttr(
        entity_id=12, variable_name="productSelectionProduct_all", display_label="Product",
        required=True, default_value="", select_type="single",
        options=_menu("APX NEXT XE SINGLE BAND"),
    )
    attrs = [feature_attr, package_type_attr, product_attr]
    filled = {"productSelectionProduct_all": "APX NEXT XE SINGLE BAND"}

    # Mirrors the real "Hide Single Pack Calmshell when...is not selected
    # as feature type" rule: fires when the feature-type attr does NOT
    # contain ICE KIT, restricting Package Type to a value real product-
    # based rules never allow for this product -- an empty intersection
    # results the moment this rule fires on a false "confirmed empty".
    disjoint_from_rule = ConstraintRule(
        rule_name="Hide Single Pack Calmshell when not ICE KIT",
        condition_attr_id=feature_attr.entity_id, condition_value="ICE KIT",
        condition_operator="8", target_attr_id=package_type_attr.entity_id,
        allowed_values=["SINGLE PACK CLAMSHELL"],
        conditions=[(feature_attr.entity_id, "ICE KIT", "8")],
    )
    # Mirrors the real "Constrain APX NEXT XE & XN" rule -- allows
    # BULK XE/SINGLE XE once this product line is selected.
    product_based_rule = ConstraintRule(
        rule_name="Constrain APX NEXT XE & XN",
        condition_attr_id=product_attr.entity_id,
        condition_value="APX NEXT XE SINGLE BAND", condition_operator="4",
        target_attr_id=package_type_attr.entity_id,
        allowed_values=["BULK XE", "SINGLE XE"],
    )

    eng = CpqEngine()

    # Case A (the bug): feature attr force-resolved to a confirmed-empty
    # selection (what the old auto_fill fallback used to produce).
    constrained_confirmed_empty = eng.apply_constraint_rules(
        attrs, [disjoint_from_rule, product_based_rule], filled=filled,
        filled_multi={"additionalSystemEnhancementFeatureType_astro": []},
    )
    assert constrained_confirmed_empty.get(package_type_attr.entity_id) == [], (
        "sanity check: a REAL confirmed-empty selection correctly satisfies "
        "disjoint-from and collapses the intersection -- proves the "
        "mechanism, not the fix"
    )

    # Case B (the fix): feature attr genuinely unresolved -- absent from
    # filled_multi entirely, exactly what the corrected auto_fill now
    # leaves behind for an ambiguous (2+ remaining options) multi-select.
    constrained_unresolved = eng.apply_constraint_rules(
        attrs, [disjoint_from_rule, product_based_rule], filled=filled,
        filled_multi={},
    )
    assert constrained_unresolved.get(package_type_attr.entity_id) == ["BULK XE", "SINGLE XE"], (
        "an unresolved (never-answered) multi-select must not satisfy a "
        "sibling rule's disjoint-from condition -- Package Type must keep "
        "its real, product-based allowed set, not collapse to empty"
    )
