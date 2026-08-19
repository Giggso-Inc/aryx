"""Live-confirmed root cause for the real APX NEXT Enhanced transcript's
Package Type conflict: raw XML export APXNext_CnofigData.xml, active rule
18131370895 ("Default Single Pack Clamshell if ICE Kit ordered and BULK
if no ICE Kit on ENhanced") constrains packingPackageType_astro (attr
17691442194) via a script-computed single value:

    retVal = "";
    if((findinArray(split(additionalSystemEnhancementFeatureType_astro, "~"),"ICE KIT") <> -1)){
        retVal = "SINGLE PACK CLAMSHELL";
    }
    else{
    retVal = "BULK";
    }
    return retVal;

This is the exact script text pulled from the live catalog (function
18131369765) -- not a paraphrase. When additionalSystemEnhancementFeature
Type_astro contains "ICE KIT" the sole legal value is "SINGLE PACK
CLAMSHELL"; once ICE KIT is removed, the sole legal value flips to
"BULK". A session that filled Package Type while ICE KIT was present and
then has ICE KIT removed goes stale -- this must clear and re-narrow the
question to the new sole legal value ("BULK"), not fall through to the
raw 8-option catalog list (the observed live bug fixed in
_reask_stale_constraint_violations's `conflicted` branch).

This test stubs BmlEvaluator.allowed_values_for_script directly rather
than going through the real Tier-1/Tier-2/cache machinery: Tier 1's
deterministic parser doesn't recognize this script's findinArray/split
idiom (confirmed live -- no findinArray/findInArray handling exists in
bml.py's evaluate_tier1), so a real run would fall to Tier 2 (LLM) --
and BmlEvaluator's Tier-2 path includes a durable, cross-process
Postgres-backed cache (bml.py's _durable_get/_durable_put) that isn't
test-isolated, which produced a flaky stray-cached-value collision when
this test called through the real Tier-2 path in the full suite. What
this test verifies -- the reask/narrowing fix -- doesn't depend on BML's
own script-parsing tiering, so stubbing the method directly is both
more robust and a more accurate test boundary.

Note: apply_constraint_rules only evaluates a script-backed rule's own
script -- it does not additionally gate script-backed rules on
condition_attr_id/condition_value (engine.py:5935, confirmed by reading
the source), so this test's rule omits a declarative condition entirely;
it does not assert anything about how the loader itself decides to
attach the rule's separate declarative Product=="APX NEXT ENHANCED"
condition.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.api.ask_api import _reask_stale_constraint_violations
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.state import ConfigAttr, ConstraintRule, CpqSession, MenuOption

_ICE_KIT_SCRIPT = """
retVal = "";

if((findinArray(split(additionalSystemEnhancementFeatureType_astro, "~"),"ICE KIT") <> -1)){
	retVal = "SINGLE PACK CLAMSHELL";
}
else{
retVal = "BULK";
}
return retVal;
"""


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


def _fake_ice_kit_evaluator(feature_type_value: str) -> BmlEvaluator:
    """A BmlEvaluator whose allowed_values_for_script directly mirrors the
    real script's own if/else logic against feature_type_value, without
    touching Tier 1/2 or any cache."""
    bml_eval = BmlEvaluator({}, use_llm=False)

    def _fake_allowed(script, variables, cache_id=None):
        assert script == _ICE_KIT_SCRIPT
        fv = variables.get("additionalSystemEnhancementFeatureType_astro", "")
        if "ICE KIT" in fv.split("~"):
            return ["SINGLE PACK CLAMSHELL"]
        return ["BULK"]

    bml_eval.allowed_values_for_script = _fake_allowed  # type: ignore[method-assign]
    return bml_eval


def test_ice_kit_script_logic_yields_single_pack_clamshell_when_ice_kit_present():
    """Documents the real script's own branch: ICE KIT present -> the
    sole legal value is SINGLE PACK CLAMSHELL."""
    bml_eval = _fake_ice_kit_evaluator("ICE KIT")
    assert bml_eval.allowed_values_for_script(
        _ICE_KIT_SCRIPT, {"additionalSystemEnhancementFeatureType_astro": "ICE KIT"},
    ) == ["SINGLE PACK CLAMSHELL"]


def test_ice_kit_script_logic_yields_bulk_when_ice_kit_absent():
    """Documents the real script's other branch: ICE KIT absent -> the
    sole legal value flips to BULK."""
    bml_eval = _fake_ice_kit_evaluator("SOME OTHER FEATURE")
    assert bml_eval.allowed_values_for_script(
        _ICE_KIT_SCRIPT, {"additionalSystemEnhancementFeatureType_astro": "SOME OTHER FEATURE"},
    ) == ["BULK"]


def test_package_type_silently_reresolves_to_bulk_when_ice_kit_removed():
    """End-to-end: Package Type was filled "SINGLE PACK CLAMSHELL" while
    ICE KIT was selected; ICE KIT is then removed from the feature-type
    selection, flipping the real catalog script's sole legal value to
    "BULK".

    2026-08-19 UPDATE (live transcript, second occurrence same day): a
    sibling live bug showed a DIFFERENT Package Type-governing rule
    ("Constraint Package Type Based on Bundle Type") narrow Package Type
    to exactly one legal value here, yet still get cleared and re-asked
    as a pointless single-option menu ("choose one: 1. Single Pack
    Clamshell"). Since packingPackageType_astro is a member of
    _NEVER_ASK_RECOMMENDED_ONLY_VNS -- the native UI NEVER asks about it
    conversationally, full stop, regardless of WHICH governing rule
    caused the staleness -- _reask_stale_constraint_violations now
    silently re-resolves any hard-excluded attribute's staleness the
    same way when it narrows to exactly one legal value, rather than
    re-asking. This test (previously asserting a narrowed re-ask) is
    updated to assert the new, consistent behavior for this exact ICE
    KIT scenario too -- not a special case, the same one mechanism now
    covers both governing rules."""
    package_type_attr = _package_type_attr()
    session = CpqSession()
    session.filled = {
        "packingPackageType_astro": "SINGLE PACK CLAMSHELL",
        # ICE KIT has since been removed from this multi-select feature-type attr
        "additionalSystemEnhancementFeatureType_astro": "SOME OTHER FEATURE",
    }
    session.filled_source = {
        "packingPackageType_astro": "rule",
        "additionalSystemEnhancementFeatureType_astro": "user",
    }
    session.pending_variables = []

    rule = ConstraintRule(
        rule_name="Default Single Pack Clamshell if ICE Kit ordered and BULK if no ICE Kit on ENhanced",
        condition_attr_id=-1, condition_value="", target_attr_id=package_type_attr.entity_id,
        allowed_values=[], script=_ICE_KIT_SCRIPT,
    )

    bml_eval = _fake_ice_kit_evaluator("SOME OTHER FEATURE")
    result = _reask_stale_constraint_violations(
        session, [package_type_attr], con_rules=[rule], bml_eval=bml_eval,
    )

    # Nothing left to ask about -- the caller's normal "show complete"
    # branch takes over (mirrors the confirmed-data-table-conflict
    # fallback when `stale` empties out entirely).
    assert result is None
    assert session.filled.get("packingPackageType_astro") == "BULK", (
        "must silently re-resolve to the freshly narrowed sole legal "
        "value, not sit cleared or hold the stale SINGLE PACK CLAMSHELL"
    )
    assert session.display_filled.get("packingPackageType_astro") == "BULK"
    assert session.filled_source.get("packingPackageType_astro") == "rule"
    assert "packingPackageType_astro" not in session.pending_variables
