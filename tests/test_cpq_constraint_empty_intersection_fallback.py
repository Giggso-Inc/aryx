"""docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_PLAN_2026_08_05.md's "Known
remaining issue" -- explicit product decision (2026-08-05): some catalogs
carry a genuine authoring gap where a constraint rule was never given a
counterpart for a newer product variant, unconditionally colliding with
that variant's own (correct) constraint and zeroing the intersection.

Real incident: for productSelectionProduct_all = "APX NEXT XE SINGLE
BAND", "Constrain APX NEXT XE & XN" (condition: this product line) allows
['BULK XE', 'SINGLE XE'] for packingPackageType_astro, but two older
ICE-KIT rules -- authored before the XE/XN line existed, never extended to
match it -- unconditionally collide: "Restrict Bulk lov...if feature type
contains ICE KIT" (condition: Feature Type intersects {ICE KIT}) allows
['BULK'], and "Hide Single Pack Calmshell...is not selected as feature
type" (condition: Feature Type disjoint from {ICE KIT}) allows ['SINGLE
PACK CLAMSHELL']. Whichever way Feature Type resolves, the full
intersection is empty -- Package Type becomes an unanswerable question.

Fix: apply_constraint_rules groups the rules that actually fired by their
condition's attribute set. When the full intersection is empty, each
candidate group's "centrality" is scored by how many rules catalog-wide
(across the full rules list, not just those active this turn) reference
that same condition attribute -- confirmed live this cleanly separates a
catalog's backbone discriminator (productSelectionProduct_all, 478
references in the real APX Next export) from an incidentally-referenced
peripheral one (additionalSystemEnhancementFeatureType_astro, 3
references). Dropping the single group with the strictly lowest score
resolves the conflict; a tie for lowest, or 2+ groups whose removal would
each independently resolve it, is genuinely ambiguous and stays empty
rather than guessing.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, ConstraintRule, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _apx_next_xe_scenario():
    feature_attr = ConfigAttr(
        entity_id=10, variable_name="additionalSystemEnhancementFeatureType_astro",
        display_label="Feature Type", required=False, default_value="",
        select_type="multi", options=_menu("ICE KIT", "DISABLE CLOUD SERVICES"),
    )
    package_type_attr = ConfigAttr(
        entity_id=11, variable_name="packingPackageType_astro", display_label="Package Type",
        required=False, default_value="", select_type="single",
        options=_menu("BULK", "BULK XE", "SINGLE XE", "SINGLE PACK CLAMSHELL"),
    )
    product_attr = ConfigAttr(
        entity_id=12, variable_name="productSelectionProduct_all", display_label="Product",
        required=True, default_value="", select_type="single",
        options=_menu("APX NEXT XE SINGLE BAND"),
    )
    attrs = [feature_attr, package_type_attr, product_attr]

    ice_kit_bulk_rule = ConstraintRule(
        rule_name="Restrict Bulk lov for package type attribute if feature type contains ICE KIT",
        condition_attr_id=feature_attr.entity_id, condition_value="ICE KIT",
        condition_operator="7", target_attr_id=package_type_attr.entity_id,
        allowed_values=["BULK"], conditions=[(feature_attr.entity_id, "ICE KIT", "7")],
    )
    ice_kit_clamshell_rule = ConstraintRule(
        rule_name="Hide Single Pack Calmshell when...is not selected as feature type",
        condition_attr_id=feature_attr.entity_id, condition_value="ICE KIT",
        condition_operator="8", target_attr_id=package_type_attr.entity_id,
        allowed_values=["SINGLE PACK CLAMSHELL"],
        conditions=[(feature_attr.entity_id, "ICE KIT", "8")],
    )
    product_based_rule = ConstraintRule(
        rule_name="Constrain APX NEXT XE & XN",
        condition_attr_id=product_attr.entity_id,
        condition_value="APX NEXT XE SINGLE BAND", condition_operator="4",
        target_attr_id=package_type_attr.entity_id,
        allowed_values=["BULK XE", "SINGLE XE"],
        conditions=[(product_attr.entity_id, "APX NEXT XE SINGLE BAND", "4")],
    )
    # Replicates the real catalog's shape: productSelectionProduct_all is
    # referenced by hundreds of OTHER "Constrain X for product Y" rules
    # catalog-wide (478 in the real APX Next export), vastly more than
    # additionalSystemEnhancementFeatureType_astro (3). Without these
    # decoys, a synthetic test with only the 2-3 Package-Type-relevant
    # rules would tie or invert the real signal -- the fallback's
    # centrality scoring is meaningless without the catalog-wide context
    # it's designed to read.
    decoy_rules = [
        ConstraintRule(
            rule_name=f"Decoy constrain rule {i}",
            condition_attr_id=product_attr.entity_id,
            condition_value="APX NEXT XE SINGLE BAND", condition_operator="4",
            target_attr_id=9000 + i, allowed_values=["DECOY"],
            conditions=[(product_attr.entity_id, "APX NEXT XE SINGLE BAND", "4")],
        )
        for i in range(20)
    ]
    return (
        attrs, package_type_attr, ice_kit_bulk_rule, ice_kit_clamshell_rule,
        product_based_rule, decoy_rules,
    )


def test_ice_kit_selected_no_longer_collapses_package_type_to_empty():
    attrs, package_type_attr, ice_kit_bulk_rule, ice_kit_clamshell_rule, product_based_rule, decoy_rules = (
        _apx_next_xe_scenario())
    filled = {"productSelectionProduct_all": "APX NEXT XE SINGLE BAND"}
    eng = CpqEngine()

    result = eng.apply_constraint_rules(
        attrs, [ice_kit_bulk_rule, product_based_rule, *decoy_rules], filled=filled,
        filled_multi={"additionalSystemEnhancementFeatureType_astro": ["ICE KIT"]},
    )
    assert result.get(package_type_attr.entity_id) == ["BULK XE", "SINGLE XE"]


def test_ice_kit_not_selected_no_longer_collapses_package_type_to_empty():
    attrs, package_type_attr, ice_kit_bulk_rule, ice_kit_clamshell_rule, product_based_rule, decoy_rules = (
        _apx_next_xe_scenario())
    filled = {"productSelectionProduct_all": "APX NEXT XE SINGLE BAND"}
    eng = CpqEngine()

    result = eng.apply_constraint_rules(
        attrs, [ice_kit_clamshell_rule, product_based_rule, *decoy_rules], filled=filled,
        filled_multi={"additionalSystemEnhancementFeatureType_astro": ["DISABLE CLOUD SERVICES"]},
    )
    assert result.get(package_type_attr.entity_id) == ["BULK XE", "SINGLE XE"]


def test_both_ice_kit_rules_would_never_both_fire_but_fallback_still_resolves_with_all_three():
    """Realistic full shape: all three rules loaded, but only one ICE-KIT
    rule's condition is ever true for a given filled state -- exercises the
    fallback with the full rule set present, not a pre-trimmed list."""
    attrs, package_type_attr, ice_kit_bulk_rule, ice_kit_clamshell_rule, product_based_rule, decoy_rules = (
        _apx_next_xe_scenario())
    filled = {"productSelectionProduct_all": "APX NEXT XE SINGLE BAND"}
    eng = CpqEngine()

    result = eng.apply_constraint_rules(
        attrs, [ice_kit_bulk_rule, ice_kit_clamshell_rule, product_based_rule, *decoy_rules], filled=filled,
        filled_multi={"additionalSystemEnhancementFeatureType_astro": ["ICE KIT"]},
    )
    assert result.get(package_type_attr.entity_id) == ["BULK XE", "SINGLE XE"]


def test_genuinely_ambiguous_two_group_conflict_stays_empty_not_guessed():
    """If dropping EITHER of two different condition-groups would each
    independently resolve the conflict, that's genuinely ambiguous -- must
    stay empty rather than arbitrarily picking one group to keep."""
    attr_a = ConfigAttr(
        entity_id=20, variable_name="conditionAttrA", display_label="A",
        required=True, default_value="", select_type="single", options=_menu("A1"),
    )
    attr_b = ConfigAttr(
        entity_id=21, variable_name="conditionAttrB", display_label="B",
        required=True, default_value="", select_type="single", options=_menu("B1"),
    )
    target_attr = ConfigAttr(
        entity_id=22, variable_name="target_astro", display_label="Target",
        required=False, default_value="", select_type="single",
        options=_menu("X", "Y", "Z"),
    )
    attrs = [attr_a, attr_b, target_attr]
    filled = {"conditionAttrA": "A1", "conditionAttrB": "B1"}

    rule_from_a = ConstraintRule(
        rule_name="Rule from A", condition_attr_id=attr_a.entity_id, condition_value="A1",
        condition_operator="4", target_attr_id=target_attr.entity_id, allowed_values=["X"],
        conditions=[(attr_a.entity_id, "A1", "4")],
    )
    rule_from_b = ConstraintRule(
        rule_name="Rule from B", condition_attr_id=attr_b.entity_id, condition_value="B1",
        condition_operator="4", target_attr_id=target_attr.entity_id, allowed_values=["Y"],
        conditions=[(attr_b.entity_id, "B1", "4")],
    )
    eng = CpqEngine()
    result = eng.apply_constraint_rules(attrs, [rule_from_a, rule_from_b], filled=filled)

    # Dropping "Rule from A" alone -> ['Y'] (non-empty); dropping "Rule from
    # B" alone -> ['X'] (non-empty) -- two independently-resolving groups,
    # genuinely ambiguous which one the catalog actually intended to win.
    assert target_attr.entity_id not in result or result[target_attr.entity_id] == []


def test_single_conflicting_group_with_no_alternative_resolution_stays_empty():
    """All contributing rules share ONE condition attribute set -- there is
    no "other" group to keep, so this is a genuine, single-source
    contradiction (not the authoring-gap shape this fallback targets) and
    must stay empty."""
    attr_a = ConfigAttr(
        entity_id=30, variable_name="conditionAttrA", display_label="A",
        required=True, default_value="", select_type="single", options=_menu("A1"),
    )
    target_attr = ConfigAttr(
        entity_id=31, variable_name="target_astro", display_label="Target",
        required=False, default_value="", select_type="single",
        options=_menu("X", "Y"),
    )
    attrs = [attr_a, target_attr]
    filled = {"conditionAttrA": "A1"}

    rule_1 = ConstraintRule(
        rule_name="Rule 1", condition_attr_id=attr_a.entity_id, condition_value="A1",
        condition_operator="4", target_attr_id=target_attr.entity_id, allowed_values=["X"],
        conditions=[(attr_a.entity_id, "A1", "4")],
    )
    rule_2 = ConstraintRule(
        rule_name="Rule 2", condition_attr_id=attr_a.entity_id, condition_value="A1",
        condition_operator="4", target_attr_id=target_attr.entity_id, allowed_values=["Y"],
        conditions=[(attr_a.entity_id, "A1", "4")],
    )
    eng = CpqEngine()
    result = eng.apply_constraint_rules(attrs, [rule_1, rule_2], filled=filled)
    assert result.get(target_attr.entity_id, []) == []
