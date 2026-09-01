"""Live bug: auto_fill()'s own "constraint narrows to exactly one legal
value -> auto-fill, never ask" mechanism only ever sees whatever
constraint evaluation was available AT THE MOMENT auto_fill() ran. A
script-backed constraint rule that depends on BmlEvaluator's Tier-2 (LLM)
path -- because Tier 1's deterministic parser doesn't support its idiom
(confirmed live: Package Type's real ICE-KIT rule, 18131370895, uses
findinArray/split, which bml.evaluate_tier1 doesn't recognize) -- can
resolve to a single legal value too late for auto_fill()'s own check to
catch it, landing the attribute in `pending` even though, by the time
its question is about to be presented, only one real answer remains.

_auto_resolve_singleton_pending is the shared fix wired into all 6 of
ask_api's independent auto_fill() call sites: one more live re-check of
pending[0]'s constraints right before it would be asked.
"""
from __future__ import annotations

from aryx.api.ask_api import _auto_resolve_singleton_pending
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.state import ConfigAttr, ConstraintRule, MenuOption

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
    bml_eval = BmlEvaluator({}, use_llm=False)

    def _fake_allowed(script, variables, cache_id=None):
        fv = variables.get("additionalSystemEnhancementFeatureType_astro", "")
        if "ICE KIT" in fv.split("~"):
            return ["SINGLE PACK CLAMSHELL"]
        return ["BULK"]

    bml_eval.allowed_values_for_script = _fake_allowed  # type: ignore[method-assign]
    return bml_eval


def test_singleton_narrowed_pending_attr_resolves_silently_instead_of_asking():
    """The exact live bug: Package Type is in `pending` (auto_fill saw it
    as unresolved), but its real constraint script has since narrowed to
    exactly one legal value. The shared helper must silently fill it and
    remove it from pending -- never asked."""
    attr = _package_type_attr()
    pending = [attr]
    filled = {"additionalSystemEnhancementFeatureType_astro": "SOME OTHER FEATURE"}
    display_filled: dict = {}
    filled_source: dict = {}
    rule = ConstraintRule(
        rule_name="Default Single Pack Clamshell if ICE Kit ordered and BULK if no ICE Kit on ENhanced",
        condition_attr_id=-1, condition_value="", target_attr_id=attr.entity_id,
        allowed_values=[], script=_ICE_KIT_SCRIPT,
    )
    bml_eval = _fake_ice_kit_evaluator("SOME OTHER FEATURE")

    result = _auto_resolve_singleton_pending(
        pending, filled, display_filled, filled_source, [rule], bml_eval,
    )

    assert result == [], "the singleton-narrowed attr must be removed from pending"
    assert filled.get("packingPackageType_astro") == "BULK"
    assert display_filled.get("packingPackageType_astro") == "BULK"
    assert filled_source.get("packingPackageType_astro") == "rule"


def test_multi_option_pending_attr_is_left_alone():
    """Regression guard: an attribute genuinely still narrowed to 2+
    legal options (or unconstrained) must stay in pending -- this helper
    only resolves the exactly-one-option case, never guesses among
    several."""
    attr = _package_type_attr()
    pending = [attr]
    filled = {"additionalSystemEnhancementFeatureType_astro": ""}
    display_filled: dict = {}
    filled_source: dict = {}

    class _NoOpConstraintRule(ConstraintRule):
        pass

    rule = ConstraintRule(
        rule_name="unconstrained probe", condition_attr_id=-1, condition_value="",
        target_attr_id=attr.entity_id, allowed_values=[], script="return \"\";",
    )
    bml_eval = BmlEvaluator({}, use_llm=False)

    result = _auto_resolve_singleton_pending(
        pending, filled, display_filled, filled_source, [rule], bml_eval,
    )

    assert result == [attr], "an unresolved/multi-option attr must remain pending"
    assert "packingPackageType_astro" not in filled


def test_multiselect_pending_attr_is_never_touched():
    """Never applied to multi-select attrs -- auto_fill's own
    "exactly one value" shortcut is single-select-only by design."""
    attr = ConfigAttr(
        entity_id=1, variable_name="someMultiSelect_astro", display_label="Some Multi",
        required=False, default_value="", select_type="multi",
        options=_menu("A", "B"),
    )
    pending = [attr]
    result = _auto_resolve_singleton_pending(
        pending, {}, {}, {}, [ConstraintRule(
            rule_name="x", condition_attr_id=-1, condition_value="",
            target_attr_id=1, allowed_values=["A"],
        )], BmlEvaluator({}, use_llm=False),
    )
    assert result == [attr]


def test_no_con_rules_or_bml_eval_is_a_safe_noop():
    attr = _package_type_attr()
    pending = [attr]
    assert _auto_resolve_singleton_pending(pending, {}, {}, {}, [], None) == pending
    assert _auto_resolve_singleton_pending(pending, {}, {}, {}, [], BmlEvaluator({})) == pending
