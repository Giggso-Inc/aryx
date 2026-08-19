"""Second, independent live occurrence of the Package Type bug the same
day (api-logs-1908 (1).log): a DIFFERENT governing rule than the ICE-KIT
one -- "Constraint Package Type Based on Bundle Type" (condition_function_
id=18988360341), keyed on packageTypeBundles_astro / modelSelectionHousing_
astro, confirmed live via `rule_trace type=constraint` -- narrowed Package
Type to exactly one legal value ("SINGLE PACK CLAMSHELL"), yet
_reask_stale_constraint_violations still cleared it and asked "Before
finishing -- Package Type is no longer valid ... choose one: 1. Single
Pack Clamshell" -- a technically-correct but pointless single-option menu.

Root cause: _hard_exclude_from_pending's own allowlist (native UI never
asks Package Type conversationally, only ever shows it read-only under
"Recommended Configuration") was wired into the 6 cascade/change call
sites and nowhere else. _reask_stale_constraint_violations is an 8th,
completely independent write path (the proactive stale-constraint recheck
that runs right before "Configuration complete") that never consulted
this allowlist at all -- it always cleared + re-asked ANY stale value,
even one already narrowed to a single legal replacement.

Fix: when a stale, non-conflicted violation's attribute is in
_NEVER_ASK_RECOMMENDED_ONLY_VNS and its freshly recomputed `allowed` set
has exactly one legal value (the same trust bar _hard_exclude_from_
pending itself uses -- 2+ values is still a real, unresolved choice, not
a computed answer), silently re-fill it with that value instead of
re-asking. Every other stale attribute in the same batch is unaffected.
"""
from __future__ import annotations

from aryx.api.ask_api import _reask_stale_constraint_violations
from aryx.cpq.state import ConfigAttr, ConstraintRule, CpqSession, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _package_type_attr() -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="packingPackageType_astro", display_label="Package Type",
        required=False, default_value="", select_type="single",
        options=_menu(
            "SINGLE", "BULK", "N/A", "DEMO KIT CASE", "SINGLE XE",
            "BULK XE", "PACK INTO DEMO KIT CASE", "SINGLE PACK CLAMSHELL",
        ),
    )


def _bundle_type_attr() -> ConfigAttr:
    return ConfigAttr(
        entity_id=2, variable_name="packageTypeBundles_astro", display_label="Bundle Type",
        required=False, default_value="", select_type="single",
        options=_menu("STANDARD BUNDLE", "PREMIUM BUNDLE"),
    )


def test_package_type_silently_reresolves_when_bundle_type_narrows_to_one_value():
    """The exact live transcript: Package Type was auto-filled earlier
    (e.g. via the ICE-KIT rule's own resolution), then Bundle Type became
    known and its own constraint narrows Package Type down to exactly
    "SINGLE PACK CLAMSHELL" -- must silently re-resolve, not re-ask a
    single-option menu."""
    package_type_attr = _package_type_attr()
    bundle_type_attr = _bundle_type_attr()
    attrs = [package_type_attr, bundle_type_attr]

    session = CpqSession()
    session.filled = {
        "packingPackageType_astro": "BULK",  # now-stale, auto-filled earlier
        "packageTypeBundles_astro": "PREMIUM BUNDLE",
    }
    session.display_filled = {
        "packingPackageType_astro": "BULK", "packageTypeBundles_astro": "PREMIUM BUNDLE",
    }
    session.filled_source = {
        "packingPackageType_astro": "rule", "packageTypeBundles_astro": "user",
    }
    session.pending_variables = []

    rule = ConstraintRule(
        rule_name="Constraint Package Type Based on Bundle Type",
        condition_attr_id=bundle_type_attr.entity_id, condition_value="PREMIUM BUNDLE",
        target_attr_id=package_type_attr.entity_id,
        allowed_values=["SINGLE PACK CLAMSHELL"], script=None,
    )

    result = _reask_stale_constraint_violations(
        session, attrs, con_rules=[rule], bml_eval=None,
    )

    assert result is None, (
        "nothing left to genuinely ask about -- must not produce a "
        "pointless single-option 'choose one: 1. Single Pack Clamshell' prompt"
    )
    assert session.filled.get("packingPackageType_astro") == "SINGLE PACK CLAMSHELL"
    assert session.display_filled.get("packingPackageType_astro") == "SINGLE PACK CLAMSHELL"
    assert session.filled_source.get("packingPackageType_astro") == "rule"
    assert "packingPackageType_astro" not in session.pending_variables


def test_non_allowlisted_attr_still_reasks_normally_when_narrowed_to_one_value():
    """Regression guard: this is a named, individually-vetted allowlist
    mechanism, not a generic 'any single-value narrowing skips the ask'
    shortcut -- an ordinary (non-hard-excluded) attribute narrowed to
    exactly one legal value must still go through the normal clear +
    re-ask flow."""
    other_attr = ConfigAttr(
        entity_id=3, variable_name="someOtherAttr_astro", display_label="Some Other Attr",
        required=False, default_value="", select_type="single", options=_menu("A", "B", "C"),
    )
    driver_attr = ConfigAttr(
        entity_id=4, variable_name="driverAttr_astro", display_label="Driver",
        required=False, default_value="", select_type="single", options=_menu("X"),
    )
    attrs = [other_attr, driver_attr]
    session = CpqSession()
    session.filled = {"someOtherAttr_astro": "B", "driverAttr_astro": "X"}
    session.display_filled = {"someOtherAttr_astro": "B", "driverAttr_astro": "X"}
    session.filled_source = {"someOtherAttr_astro": "rule", "driverAttr_astro": "user"}
    session.pending_variables = []

    rule = ConstraintRule(
        rule_name="unrelated narrowing rule",
        condition_attr_id=driver_attr.entity_id, condition_value="X",
        target_attr_id=other_attr.entity_id, allowed_values=["A"], script=None,
    )

    result = _reask_stale_constraint_violations(
        session, attrs, con_rules=[rule], bml_eval=None,
    )

    assert result is not None
    assert "someOtherAttr_astro" not in session.filled
    assert session.pending_variables[0] == "someOtherAttr_astro"
    assert "A" in result


def test_two_or_more_remaining_values_still_reasks_even_when_allowlisted():
    """A hard-excluded attribute whose staleness narrows to 2+ remaining
    legal values is still an unresolved choice, not a computed answer --
    must not be silently guessed either, only an exact single-value
    resolution counts as real justification (mirrors _hard_exclude_from_
    pending's own len(narrowed) == 1 trust bar)."""
    package_type_attr = _package_type_attr()
    bundle_type_attr = _bundle_type_attr()
    attrs = [package_type_attr, bundle_type_attr]

    session = CpqSession()
    session.filled = {
        "packingPackageType_astro": "DEMO KIT CASE",
        "packageTypeBundles_astro": "STANDARD BUNDLE",
    }
    session.display_filled = {
        "packingPackageType_astro": "DEMO KIT CASE", "packageTypeBundles_astro": "STANDARD BUNDLE",
    }
    session.filled_source = {
        "packingPackageType_astro": "rule", "packageTypeBundles_astro": "user",
    }
    session.pending_variables = []

    rule = ConstraintRule(
        rule_name="Constraint Package Type Based on Bundle Type",
        condition_attr_id=bundle_type_attr.entity_id, condition_value="STANDARD BUNDLE",
        target_attr_id=package_type_attr.entity_id,
        allowed_values=["SINGLE", "BULK"], script=None,
    )

    result = _reask_stale_constraint_violations(
        session, attrs, con_rules=[rule], bml_eval=None,
    )

    assert result is not None
    assert "packingPackageType_astro" not in session.filled
    assert session.pending_variables[0] == "packingPackageType_astro"
