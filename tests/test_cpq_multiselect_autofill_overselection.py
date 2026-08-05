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

Fix 2 (superseded by an explicit product decision below): an interim fix
made an ambiguous (2+ remaining options), constrained multi-select fall
through to `pending` (asked) instead of a false "confirmed empty" --
because _filled_by_rule_id treats an explicit [] as a real, known-empty
value, which let a sibling rule keyed on "does NOT contain value X"
(operator "8", disjoint-from) fire on it as if the customer had confirmed
nothing. Live-verifying that interim fix surfaced a real new question
("Feature Type") the product owner did not want asked. Explicit decision
(HITL-confirmed): prefer the XML default_value when it's still a
currently-valid option; otherwise default to empty and do not ask --
accepting the disjoint-from risk Fix 2 had closed, as a deliberate
trade for fewer conversational questions (see engine.py's
auto_fill docstring and the plan doc's "explicit product decision"
addendum for the full rationale and the accepted risk).
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, ConstraintRule, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def test_multiselect_with_several_constrained_options_and_no_default_defaults_to_empty():
    """Replays the real "additionalSystemEnhancementFeatureType_astro"
    shape: a near-universal constraint narrows 11 real options down to 9,
    and the attribute has no default_value in the raw XML -- must NOT
    auto-select all 9, and (per the explicit product decision) must
    default to empty rather than asking."""
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

    assert multi.get("additionalSystemEnhancementFeatureType_astro") == [], (
        "no matching default_value and several remaining options -- must "
        "not auto-select all of them, and per the explicit product "
        "decision must default to empty rather than asking"
    )


def test_multiselect_with_several_constrained_options_and_a_default_uses_the_default():
    """A constrained, ambiguous multi-select whose XML default_value IS
    still one of the currently-valid options must auto-select just that
    default -- not all remaining options, not empty."""
    attr = ConfigAttr(
        entity_id=5, variable_name="someOptionalMulti_astro", display_label="Some Optional Multi",
        required=False, default_value="OPTION B", select_type="multi",
        options=_menu("OPTION A", "OPTION B", "OPTION C", "OPTION D"),
    )
    constrained_opts = {5: ["OPTION A", "OPTION B", "OPTION C"]}  # 3 remain, default among them

    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=constrained_opts,
        governed_ids={5}, rule_governed_ids={5}, already_filled_multi=multi,
    )

    assert multi.get("someOptionalMulti_astro") == ["OPTION B"]


def test_multiselect_default_value_excluded_by_constraint_falls_back_to_empty():
    """If the constraint has excluded the raw default_value from the
    currently-valid set, it must never be selected anyway (that would
    violate the active constraint) -- falls back to empty instead."""
    attr = ConfigAttr(
        entity_id=6, variable_name="anotherOptionalMulti_astro", display_label="Another Optional Multi",
        required=False, default_value="OPTION Z", select_type="multi",
        options=_menu("OPTION X", "OPTION Y", "OPTION Z"),
    )
    constrained_opts = {6: ["OPTION X", "OPTION Y"]}  # OPTION Z (the default) is excluded

    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=constrained_opts,
        governed_ids={6}, rule_governed_ids={6}, already_filled_multi=multi,
    )

    assert multi.get("anotherOptionalMulti_astro") == []


def test_multiselect_with_no_menu_options_and_a_default_value_does_not_crash():
    """Regression (live incident, "APX NEXT All Band" order): a multi-
    select attr reaching the ambiguous-default fallback with an EMPTY
    options list never enters the sibling `if not value and attr.options:`
    block above, so `valid_opts` from that block is never assigned this
    iteration. This attr's own default_value is valid on its own terms
    but an active constraint excludes it (the generic default_value step
    a few lines above this one correctly declines to auto-lock it in),
    so `value` stays empty and falls all the way through to this branch
    -- where referencing `valid_opts` directly threw UnboundLocalError in
    production. Must default to empty without crashing."""
    attr = ConfigAttr(
        entity_id=7, variable_name="noOptionsMulti_astro", display_label="No Options Multi",
        required=False, default_value="SOME DEFAULT", select_type="multi",
        options=[],
    )
    constrained_opts = {7: ["SOMETHING ELSE ENTIRELY"]}  # excludes the default_value
    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=constrained_opts,
        governed_ids={7}, rule_governed_ids={7}, already_filled_multi=multi,
    )
    assert multi.get("noOptionsMulti_astro") == []


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
    defaults to empty (unchanged pre-existing behavior)."""
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


def test_confirmed_empty_multiselect_can_satisfy_a_sibling_disjoint_from_rule():
    """Documents the KNOWN, ACCEPTED risk of the explicit product decision
    above (not a bug to fix): once an ambiguous multi-select defaults to
    [], _filled_by_rule_id reports that as a real, known-empty value, so a
    sibling ConstraintRule keyed on "does NOT contain value X" (operator
    "8", disjoint-from) can fire on it exactly as if the customer had
    confirmed nothing. This is the same mechanism that collapsed Package
    Type live via a rule unrelated to the ICE-KIT one Fix 1 addressed
    (docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_PLAN_2026_08_05.md's
    "Known remaining issue" section) -- kept here as a regression/
    documentation test of the mechanism itself, at the
    apply_constraint_rules level, independent of what auto_fill currently
    chooses to do with it."""
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

    # A confirmed/defaulted-empty feature attr satisfies disjoint-from and
    # collapses the intersection to empty -- the accepted, documented risk.
    constrained_confirmed_empty = eng.apply_constraint_rules(
        attrs, [disjoint_from_rule, product_based_rule], filled=filled,
        filled_multi={"additionalSystemEnhancementFeatureType_astro": []},
    )
    assert constrained_confirmed_empty.get(package_type_attr.entity_id) == []

    # A genuinely unresolved (absent from filled_multi entirely) attr must
    # NOT satisfy disjoint-from -- Package Type keeps its real allowed set.
    # This is what auto_fill would leave behind for a REQUIRED multi-select
    # (never defaulted, always falls through to pending) -- contrast with
    # the non-required case above, which auto_fill now defaults to [].
    constrained_unresolved = eng.apply_constraint_rules(
        attrs, [disjoint_from_rule, product_based_rule], filled=filled,
        filled_multi={},
    )
    assert constrained_unresolved.get(package_type_attr.entity_id) == ["BULK XE", "SINGLE XE"]
