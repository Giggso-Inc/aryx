"""docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md §4.1's own deferred
follow-up, finally built: "surfacing [a stale constraint violation] to the
user directly is a separate, not-yet-built follow-up."

Live incident: `pending` only tracks attributes never answered at all --
it has no idea whether an ALREADY-answered attribute's value is still
valid under the currently-active constraints. Before this fix, that
recheck only ever ran once "confirm" was said, so a stale value left
behind by any bug (e.g. the recommendation-rule oscillation fixed
earlier this session) could make the bot announce "Configuration
complete" while holding an already-invalid value, only corrected one
full turn later.

_reask_stale_constraint_violations runs the SAME check ("confirm"'s own
bom_gate.recheck_constraints) right before a "Configuration complete"
response would be shown, so the correction happens immediately instead.
"""
from __future__ import annotations

from aryx.api.ask_api import _reask_stale_constraint_violations
from aryx.cpq.state import ConfigAttr, ConstraintRule, CpqSession, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def test_no_active_constraint_rules_is_a_noop():
    session = CpqSession()
    assert _reask_stale_constraint_violations(session, attrs=[], con_rules=[], bml_eval=None) is None


def test_stale_value_is_cleared_and_reasked_instead_of_shown_complete():
    service_type_attr = ConfigAttr(
        entity_id=1, variable_name="serviceTypeAdditionalDMSCoverage_astro",
        display_label="Service Type", required=False, default_value="",
        select_type="single",
        options=_menu("ADVANCED", "ESSENTIAL", "ESSENTIAL WITH ACCIDENTAL DAMAGE"),
    )
    # Real condition attr, present in `attrs` -- apply_constraint_rules
    # resolves condition_attr_id against ConfigAttr.entity_id/source_id
    # via _filled_by_rule_id, not an arbitrary id.
    product_attr = ConfigAttr(
        entity_id=2, variable_name="productSelectionProduct_all", display_label="Product",
        required=True, default_value="", select_type="single", options=_menu("APX NEXT MULTI"),
    )
    attrs = [service_type_attr, product_attr]
    session = CpqSession()
    session.filled = {
        "serviceTypeAdditionalDMSCoverage_astro": "ADVANCED",
        "productSelectionProduct_all": "APX NEXT MULTI",
    }
    session.display_filled = {"serviceTypeAdditionalDMSCoverage_astro": "Advanced"}
    session.filled_source = {"serviceTypeAdditionalDMSCoverage_astro": "rule"}
    session.pending_variables = []
    session.status = "awaiting_approval"

    # Mirrors the real "Constrain rule for APX Next" -- fires whenever any
    # product is selected (condition: productSelectionProduct_all <> "").
    con_rule = ConstraintRule(
        rule_name="Constrain rule for APX Next",
        condition_attr_id=product_attr.entity_id, condition_value="",
        condition_operator="3", target_attr_id=service_type_attr.entity_id,
        allowed_values=["ESSENTIAL", "ESSENTIAL WITH ACCIDENTAL DAMAGE"],
    )

    result = _reask_stale_constraint_violations(
        session, attrs, con_rules=[con_rule], bml_eval=None,
    )

    assert result is not None
    assert "no longer valid" in result
    assert "serviceTypeAdditionalDMSCoverage_astro" not in session.filled, (
        "the stale value must be cleared, not left in place"
    )
    assert session.pending_variables[0] == "serviceTypeAdditionalDMSCoverage_astro"
    assert session.status == "configuring"
    assert session.complete is False


def test_still_valid_value_is_left_alone():
    """Regression: a value that's still within the active constraint must
    never be touched -- the caller proceeds with its normal 'complete'
    branch unchanged."""
    service_type_attr = ConfigAttr(
        entity_id=1, variable_name="serviceTypeAdditionalDMSCoverage_astro",
        display_label="Service Type", required=False, default_value="",
        select_type="single",
        options=_menu("ADVANCED", "ESSENTIAL", "ESSENTIAL WITH ACCIDENTAL DAMAGE"),
    )
    attrs = [service_type_attr]
    session = CpqSession()
    session.filled = {"serviceTypeAdditionalDMSCoverage_astro": "ESSENTIAL"}
    session.filled_source = {"serviceTypeAdditionalDMSCoverage_astro": "default"}

    con_rule = ConstraintRule(
        rule_name="Constrain rule for APX Next",
        condition_attr_id=99, condition_value="", condition_operator="3",
        target_attr_id=service_type_attr.entity_id,
        allowed_values=["ESSENTIAL", "ESSENTIAL WITH ACCIDENTAL DAMAGE"],
    )

    result = _reask_stale_constraint_violations(
        session, attrs, con_rules=[con_rule], bml_eval=None,
    )
    assert result is None
    assert session.filled.get("serviceTypeAdditionalDMSCoverage_astro") == "ESSENTIAL"


def test_genuine_conflict_reports_instead_of_asking_an_unanswerable_question():
    """Live regression this fix must NOT reintroduce: if the recomputed
    allowed set is ALSO empty (2+ active constraints genuinely conflict),
    this is not a stale-but-fixable value -- asking would just reproduce
    the exact "Please provide a value" dead-end this session's other
    fixes exist to prevent. Must report the conflict, mutate nothing."""
    package_type_attr = ConfigAttr(
        entity_id=1, variable_name="packingPackageType_astro", display_label="Package Type",
        required=False, default_value="", select_type="single",
        options=_menu("BULK XE", "SINGLE XE", "BULK", "SINGLE PACK CLAMSHELL"),
    )
    attrs = [package_type_attr]
    session = CpqSession()
    session.filled = {"packingPackageType_astro": "BULK"}
    session.filled_source = {"packingPackageType_astro": "rule"}
    session.pending_variables = []

    rule_a = ConstraintRule(
        rule_name="Constrain APX NEXT XE & XN",
        condition_attr_id=98, condition_value="XE", condition_operator="4",
        target_attr_id=package_type_attr.entity_id,
        allowed_values=["BULK XE", "SINGLE XE"],
    )
    rule_b = ConstraintRule(
        rule_name="Restrict Bulk lov...ICE KIT",
        condition_attr_id=97, condition_value="ICE KIT", condition_operator="7",
        target_attr_id=package_type_attr.entity_id,
        allowed_values=["BULK"],
    )
    # Give both rules a real condition attr present in `attrs` -- apply_
    # constraint_rules resolves condition_attr_id against ConfigAttr.
    # entity_id/source_id via _filled_by_rule_id, not an arbitrary id.
    cond_a_attr = ConfigAttr(
        entity_id=98, variable_name="condA", display_label="Cond A",
        required=True, default_value="", select_type="single", options=_menu("XE"),
    )
    cond_b_attr = ConfigAttr(
        entity_id=97, variable_name="condB", display_label="Cond B",
        required=False, default_value="", select_type="multi", options=_menu("ICE KIT"),
    )
    attrs = [package_type_attr, cond_a_attr, cond_b_attr]
    session.filled["condA"] = "XE"
    session.filled_multi = {"condB": ["ICE KIT"]}

    result = _reask_stale_constraint_violations(
        session, attrs, con_rules=[rule_a, rule_b], bml_eval=None,
    )

    assert result is not None
    assert "Rule conflict detected" in result
    assert "packingPackageType_astro" in session.filled, (
        "a genuine conflict must not clear the value -- there's no "
        "productive replacement to ask for"
    )
    assert session.pending_variables == [], "must not mutate pending on a genuine conflict"
