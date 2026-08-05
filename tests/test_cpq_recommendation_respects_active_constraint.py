"""docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_PLAN_2026_08_05.md follow-up.

Live incident: changing Hardware Version correctly narrowed Service Type
(Additional DMS Coverage) to 3 different, mutually-exclusive real options
via an active ConstraintRule keyed on Hardware Version. But auto_fill's
"already-satisfied recommendation" check (step 2, checked BEFORE the
default_value step) matched a completely separate RecommendationRule
("Default Service Type based on Solution Type selected", condition
depends on Solution Type, never on Hardware Version) against the
attribute's full, UNFILTERED menu -- so it kept reasserting the OLD value
("ADVANCED") every single turn, even though the active constraint had
already ruled it out. This silently produced an internally inconsistent
"Configuration complete" (nothing was left pending, since the
recommendation "resolved" the attribute) that a separate consistency
check only caught one full turn later, when the customer said "confirm".

Fix 1: the step-2 recommendation check now filters `attr.options` down to
the currently-active constrained set (same pattern the later, already-
correct is_governed-branch recommendation check uses) before checking
whether the recommendation's value is still actually selectable.

Fix 2 (the actual root cause, found live-verifying Fix 1 alone still
didn't resolve the symptom): evaluate_rules_loop runs "hide -> auto_fill
-> recommend -> constrain" EACH pass. apply_recommendation_rules has zero
constraint awareness at all -- it only checks "is the target currently
filled", never "is this specific value still valid" -- and runs BEFORE
apply_constraint_rules recomputes the current pass's allowed set. So even
with Fix 1 in place, the moment auto_fill's own re-validation correctly
dropped the stale value, THIS function immediately refilled it again on
the very next pass, before constraints had a chance to exclude it (using
this pass's not-yet-updated info) -- an every-pass oscillation
(drop -> refill -> drop -> refill) that evaluate_rules_loop's fixed-point
check (KEY set equality, not value equality) couldn't detect, so it
"converged" holding whichever pass's refilled-but-wrong value happened to
still be present when the loop hit its `_MAX_LOOPS` cutoff.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, ConstraintRule, MenuOption, RecommendationRule


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def test_recommendation_never_reasserts_a_value_an_active_constraint_excludes():
    service_type_attr = ConfigAttr(
        entity_id=1, variable_name="serviceTypeAdditionalDMSCoverage_astro",
        display_label="Service Type", required=False, default_value="",
        select_type="single",
        options=_menu("ADVANCED", "ESSENTIAL", "ESSENTIAL WITH ACCIDENTAL DAMAGE"),
    )
    solution_type_attr = ConfigAttr(
        entity_id=2, variable_name="solutionTypeDevices_astro", display_label="Solution Type",
        required=True, default_value="", select_type="single", options=_menu("CLOUD RC"),
    )
    attrs = [service_type_attr, solution_type_attr]
    filled = {"solutionTypeDevices_astro": "CLOUD RC"}

    # Mirrors the real "Default Service Type based on Solution Type
    # selected" rule: unconditionally recommends ADVANCED whenever
    # Solution Type is CLOUD RC -- its own condition never depends on
    # Hardware Version at all.
    rec_rule = RecommendationRule(
        rule_name="Default Service Type based on Solution Type selected",
        condition_attr_id=solution_type_attr.entity_id, condition_value="CLOUD RC",
        condition_operator="4", target_attr_id=service_type_attr.entity_id,
        recommended_value="ADVANCED",
    )
    # Mirrors the real constraint a Hardware Version change activates --
    # ADVANCED is no longer one of the currently-valid options.
    constrained_opts = {service_type_attr.entity_id: ["ESSENTIAL", "ESSENTIAL WITH ACCIDENTAL DAMAGE"]}

    eng = CpqEngine()
    filled_out, display_out, pending = eng.auto_fill(
        attrs, hints={}, already_filled=filled, constrained_opts=constrained_opts,
        governed_ids={service_type_attr.entity_id, solution_type_attr.entity_id},
        rule_governed_ids={service_type_attr.entity_id},
        rec_rules=[rec_rule],
    )

    assert filled_out.get("serviceTypeAdditionalDMSCoverage_astro") != "ADVANCED", (
        "a recommendation rule must never reassert a value a DIFFERENT, "
        "currently-active constraint has already excluded"
    )
    assert filled_out.get("serviceTypeAdditionalDMSCoverage_astro") in (
        "ESSENTIAL", "ESSENTIAL WITH ACCIDENTAL DAMAGE",
    ), "must fall through to a value that's actually still valid"


def test_recommendation_still_applies_when_its_value_remains_valid():
    """Regression: the fix must not break the normal, correct case -- a
    recommendation whose value IS still within the active constraint (or
    when there's no active constraint at all) still applies as before."""
    service_type_attr = ConfigAttr(
        entity_id=1, variable_name="serviceTypeAdditionalDMSCoverage_astro",
        display_label="Service Type", required=False, default_value="",
        select_type="single",
        options=_menu("ADVANCED", "ESSENTIAL", "ESSENTIAL WITH ACCIDENTAL DAMAGE"),
    )
    solution_type_attr = ConfigAttr(
        entity_id=2, variable_name="solutionTypeDevices_astro", display_label="Solution Type",
        required=True, default_value="", select_type="single", options=_menu("CLOUD RC"),
    )
    attrs = [service_type_attr, solution_type_attr]
    filled = {"solutionTypeDevices_astro": "CLOUD RC"}

    rec_rule = RecommendationRule(
        rule_name="Default Service Type based on Solution Type selected",
        condition_attr_id=solution_type_attr.entity_id, condition_value="CLOUD RC",
        condition_operator="4", target_attr_id=service_type_attr.entity_id,
        recommended_value="ADVANCED",
    )

    eng = CpqEngine()
    filled_out, _display, _pending = eng.auto_fill(
        attrs, hints={}, already_filled=filled, constrained_opts=None,
        governed_ids={service_type_attr.entity_id, solution_type_attr.entity_id},
        rule_governed_ids={service_type_attr.entity_id},
        rec_rules=[rec_rule],
    )

    assert filled_out.get("serviceTypeAdditionalDMSCoverage_astro") == "ADVANCED"


def test_resync_stale_recommendations_never_corrects_into_a_constraint_excluded_value():
    """Fix 3, in isolation: this was the ACTUAL mechanism reproducing the
    live bug end-to-end -- auto_fill correctly fell back to "ESSENTIAL"
    once a constraint excluded "ADVANCED", but resync_stale_recommendations
    (same pass, right after apply_recommendation_rules) saw its own
    unrelated condition (Solution Type) still held and "corrected" the
    value straight back to the excluded "ADVANCED", with zero constraint
    awareness, every single pass."""
    service_type_attr = ConfigAttr(
        entity_id=1, variable_name="serviceTypeAdditionalDMSCoverage_astro",
        display_label="Service Type", required=False, default_value="",
        select_type="single",
        options=_menu("ADVANCED", "ESSENTIAL", "ESSENTIAL WITH ACCIDENTAL DAMAGE"),
    )
    solution_type_attr = ConfigAttr(
        entity_id=2, variable_name="solutionTypeDevices_astro", display_label="Solution Type",
        required=True, default_value="", select_type="single", options=_menu("CLOUD RC"),
    )
    attrs = [service_type_attr, solution_type_attr]
    # auto_fill already correctly fell back to ESSENTIAL this pass.
    filled = {"solutionTypeDevices_astro": "CLOUD RC", "serviceTypeAdditionalDMSCoverage_astro": "ESSENTIAL"}
    filled_source = {"serviceTypeAdditionalDMSCoverage_astro": "default"}
    rec_rule = RecommendationRule(
        rule_name="Default Service Type based on Solution Type selected",
        condition_attr_id=solution_type_attr.entity_id, condition_value="CLOUD RC",
        condition_operator="4", target_attr_id=service_type_attr.entity_id,
        recommended_value="ADVANCED",
    )
    constrained_opts = {service_type_attr.entity_id: ["ESSENTIAL", "ESSENTIAL WITH ACCIDENTAL DAMAGE"]}

    eng = CpqEngine()
    corrections = eng.resync_stale_recommendations(
        attrs, filled, filled_source, [rec_rule], constrained_opts=constrained_opts,
    )
    assert corrections == {}, "must never 'correct' a valid value into one the active constraint excludes"

    # Regression: with no active constraint, the resync still works as before.
    corrections_unconstrained = eng.resync_stale_recommendations(
        attrs, filled, filled_source, [rec_rule], constrained_opts=None,
    )
    assert corrections_unconstrained.get("serviceTypeAdditionalDMSCoverage_astro") == ("ADVANCED", "ADVANCED")


def test_apply_recommendation_rules_never_reasserts_a_constraint_excluded_value():
    """Fix 2, in isolation: apply_recommendation_rules itself must decline
    to fire when its recommended value isn't in the currently-known
    active constrained set for that target -- the actual mechanism that
    kept undoing auto_fill's correct drop every pass."""
    service_type_attr = ConfigAttr(
        entity_id=1, variable_name="serviceTypeAdditionalDMSCoverage_astro",
        display_label="Service Type", required=False, default_value="",
        select_type="single",
        options=_menu("ADVANCED", "ESSENTIAL", "ESSENTIAL WITH ACCIDENTAL DAMAGE"),
    )
    solution_type_attr = ConfigAttr(
        entity_id=2, variable_name="solutionTypeDevices_astro", display_label="Solution Type",
        required=True, default_value="", select_type="single", options=_menu("CLOUD RC"),
    )
    attrs = [service_type_attr, solution_type_attr]
    filled = {"solutionTypeDevices_astro": "CLOUD RC"}
    rec_rule = RecommendationRule(
        rule_name="Default Service Type based on Solution Type selected",
        condition_attr_id=solution_type_attr.entity_id, condition_value="CLOUD RC",
        condition_operator="4", target_attr_id=service_type_attr.entity_id,
        recommended_value="ADVANCED",
    )
    constrained_opts = {service_type_attr.entity_id: ["ESSENTIAL", "ESSENTIAL WITH ACCIDENTAL DAMAGE"]}

    eng = CpqEngine()
    new_fills = eng.apply_recommendation_rules(
        attrs, filled, [rec_rule], constrained_opts=constrained_opts,
    )
    assert "serviceTypeAdditionalDMSCoverage_astro" not in new_fills

    # Regression: with no active constraint at all (None), or a constraint
    # that still allows the recommended value, it fires exactly as before.
    new_fills_unconstrained = eng.apply_recommendation_rules(
        attrs, filled, [rec_rule], constrained_opts=None,
    )
    assert new_fills_unconstrained.get("serviceTypeAdditionalDMSCoverage_astro") == ("ADVANCED", "ADVANCED")

    new_fills_still_allowed = eng.apply_recommendation_rules(
        attrs, filled, [rec_rule],
        constrained_opts={service_type_attr.entity_id: ["ADVANCED", "ESSENTIAL"]},
    )
    assert new_fills_still_allowed.get("serviceTypeAdditionalDMSCoverage_astro") == ("ADVANCED", "ADVANCED")


def test_evaluate_rules_loop_does_not_oscillate_between_drop_and_reassert():
    """End-to-end replay of the real bug through evaluate_rules_loop's own
    fixed-point iteration: a RecommendationRule whose condition is
    unrelated to Hardware Version, and a ConstraintRule keyed on Hardware
    Version that excludes the recommendation's value once a specific
    Hardware Version is selected. Before Fix 2, this oscillated
    drop-then-refill every pass and settled on the wrong (constraint-
    excluded) value; must now correctly converge to an empty/unfilled
    (never-arbitrarily-guessed) state instead."""
    service_type_attr = ConfigAttr(
        entity_id=1, variable_name="serviceTypeAdditionalDMSCoverage_astro",
        display_label="Service Type", required=False, default_value="",
        select_type="single",
        options=_menu("ADVANCED", "ESSENTIAL", "ESSENTIAL WITH ACCIDENTAL DAMAGE"),
    )
    solution_type_attr = ConfigAttr(
        entity_id=2, variable_name="solutionTypeDevices_astro", display_label="Solution Type",
        required=True, default_value="", select_type="single", options=_menu("CLOUD RC"),
    )
    hw_version_attr = ConfigAttr(
        entity_id=3, variable_name="hWVersion_astro", display_label="Hardware Version",
        required=True, default_value="", select_type="single",
        options=_menu("NEXT STANDARD LTE ONLY", "NEXT ENHANCED LTE PLUS 5G"),
    )
    attrs = [service_type_attr, solution_type_attr, hw_version_attr]
    filled = {
        "solutionTypeDevices_astro": "CLOUD RC",
        "hWVersion_astro": "NEXT ENHANCED LTE PLUS 5G",
    }

    rec_rule = RecommendationRule(
        rule_name="Default Service Type based on Solution Type selected",
        condition_attr_id=solution_type_attr.entity_id, condition_value="CLOUD RC",
        condition_operator="4", target_attr_id=service_type_attr.entity_id,
        recommended_value="ADVANCED",
    )
    con_rule = ConstraintRule(
        rule_name="Set Default Service Type Essential for APX Next Enhanced",
        condition_attr_id=hw_version_attr.entity_id, condition_value="NEXT ENHANCED LTE PLUS 5G",
        condition_operator="4", target_attr_id=service_type_attr.entity_id,
        allowed_values=["ESSENTIAL", "ESSENTIAL WITH ACCIDENTAL DAMAGE"],
    )

    eng = CpqEngine()
    _visible, filled_out, _display, _constrained = eng.evaluate_rules_loop(
        attrs, hints={}, filled=filled, hiding_rules=[], rec_rules=[rec_rule],
        con_rules=[con_rule],
    )

    assert filled_out.get("serviceTypeAdditionalDMSCoverage_astro") != "ADVANCED", (
        "must never converge on a value a currently-active constraint has "
        "already excluded, regardless of which pass the fixed-point loop "
        "happens to stop at"
    )
