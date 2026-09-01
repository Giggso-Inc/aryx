"""Live-confirmed root cause: the native Motorola APX NEXT UI never asks
about Package Type as a conversational question at all -- it only ever
appears under the passive, system-computed "Recommended Configuration"
section (with an "Edit" override affordance), never under "Mandatory
User Input" (confirmed against the real product screenshots). No
database flag distinguishes the two sections in this catalog (confirmed
live: zero BmConfigLayoutAttrAssoc rows exist for any attribute here),
so the earlier timing-dependent fixes (_auto_resolve_singleton_pending,
the Attrsequence-required allowlist) narrow the gap but can't guarantee
it in every case -- Package Type's real constraint script depends on
BmlEvaluator's Tier-2 (LLM) path, and a genuine catalog-duplicate-option
matching bug then made it unanswerable from chat entirely once it did
reach `pending` ("Bulk" rejected against a list that visibly contains
"Bulk"). _hard_exclude_from_pending is the backstop: never let it reach
`pending` at all, regardless of whether the timing-dependent fill
happened to catch it first.
"""
from __future__ import annotations

from aryx.api.ask_api import _hard_exclude_from_pending
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.state import ConfigAttr, ConstraintRule, MenuOption, RecommendationRule

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


def test_package_type_never_reaches_pending_even_when_constraint_resolves():
    """Common case: the real constraint DOES resolve (matches the
    already-fixed _auto_resolve_singleton_pending scenario), but the
    hard exclusion should still be the one to remove it -- both paths
    must agree on the same resolved value."""
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

    result = _hard_exclude_from_pending(
        pending, filled, display_filled, filled_source, [rule], bml_eval,
    )

    assert result == []
    assert filled.get("packingPackageType_astro") == "BULK"
    assert display_filled.get("packingPackageType_astro") == "BULK"


def test_package_type_stays_pending_when_nothing_justifies_a_value():
    """PR #215 review (C1): when neither a constraint nor a catalog
    default resolves Package Type, it must NOT be blind-picked from its
    8 genuinely different real options (SINGLE/BULK/N/A/DEMO KIT CASE/
    ...) -- that's exactly the "guess among real business choices with
    no justification" failure mode _no_real_fill_justification/
    _BLIND_FILL_RISK_ACCEPTED_VNS (engine.py) exist to prevent. It must
    stay in `pending` and still get asked."""
    attr = _package_type_attr()
    pending = [attr]
    filled: dict = {}
    display_filled: dict = {}
    filled_source: dict = {}
    # No constraint rules at all -- nothing can narrow it, no default_value either.
    result = _hard_exclude_from_pending(
        pending, filled, display_filled, filled_source, [], None,
    )

    assert result == [attr], "with nothing justifying a value, it must still be asked"
    assert "packingPackageType_astro" not in filled


def test_package_type_stays_pending_when_constraint_is_ambiguous():
    """A constraint that narrows to 2+ remaining legal values is still
    an unresolved choice among real options, not a computed answer --
    must not be blind-picked either, only an exact single-value
    resolution counts as real justification."""
    attr = _package_type_attr()
    pending = [attr]
    filled: dict = {}
    display_filled: dict = {}
    filled_source: dict = {}
    rule = ConstraintRule(
        rule_name="ambiguous probe", condition_attr_id=-1, condition_value="",
        target_attr_id=attr.entity_id, allowed_values=[],
        script='return "SINGLE|^|BULK";',
    )
    bml_eval = BmlEvaluator({}, use_llm=False)
    result = _hard_exclude_from_pending(
        pending, filled, display_filled, filled_source, [rule], bml_eval,
    )
    assert result == [attr]
    assert "packingPackageType_astro" not in filled


def test_unrelated_attr_in_pending_is_left_alone():
    """Regression guard: this is a named, single-attribute hard
    exclusion, not a generic 'skip anything hard to resolve' mechanism
    -- any other attribute in `pending` must be completely untouched."""
    other_attr = ConfigAttr(
        entity_id=2, variable_name="someOtherAttr_astro", display_label="Some Other Attr",
        required=False, default_value="", select_type="single",
        options=_menu("A", "B"),
    )
    pending = [other_attr]
    filled: dict = {}
    result = _hard_exclude_from_pending(
        pending, filled, {}, {}, [], None,
    )
    assert result == [other_attr]
    assert "someOtherAttr_astro" not in filled


def test_package_type_resolved_from_middle_of_pending_list():
    """_hard_exclude_from_pending scans the WHOLE pending list, not just
    the head -- unlike _auto_resolve_singleton_pending, which only ever
    looks at pending[0]. Uses a real single-value-resolving constraint
    (rather than nothing at all) since an unjustified guess must NOT be
    made -- see test_package_type_stays_pending_when_nothing_justifies_
    a_value for that case."""
    package_type = _package_type_attr()
    before_attr = ConfigAttr(
        entity_id=2, variable_name="beforeAttr_astro", display_label="Before",
        required=False, default_value="", select_type="single", options=_menu("X"),
    )
    after_attr = ConfigAttr(
        entity_id=3, variable_name="afterAttr_astro", display_label="After",
        required=False, default_value="", select_type="single", options=_menu("Y"),
    )
    pending = [before_attr, package_type, after_attr]
    filled: dict = {"additionalSystemEnhancementFeatureType_astro": "SOME OTHER FEATURE"}
    rule = ConstraintRule(
        rule_name="Default Single Pack Clamshell if ICE Kit ordered and BULK if no ICE Kit on ENhanced",
        condition_attr_id=-1, condition_value="", target_attr_id=package_type.entity_id,
        allowed_values=[], script=_ICE_KIT_SCRIPT,
    )
    bml_eval = _fake_ice_kit_evaluator("SOME OTHER FEATURE")
    result = _hard_exclude_from_pending(
        pending, filled, {}, {}, [rule], bml_eval,
    )
    assert result == [before_attr, after_attr]
    assert filled.get("packingPackageType_astro") == "BULK"


def test_package_type_governing_rule_loads_as_recommendation_not_constraint():
    """Live-confirmed: Package Type's real ICE-KIT rule (18131370895)
    loads as a RecommendationRule in the real engine (CpqEngine's own
    set_type-based classification), not a ConstraintRule -- so passing
    it only via `con_rules` (the pre-fix shape) would never resolve
    Package Type at all, regardless of any variable-handling fix. This
    proves the rec_rules path alone is sufficient."""
    attr = _package_type_attr()
    pending = [attr]
    filled = {"additionalSystemEnhancementFeatureType_astro": "SOME OTHER FEATURE"}
    display_filled: dict = {}
    filled_source: dict = {}
    rule = RecommendationRule(
        rule_name="Default Single Pack Clamshell if ICE Kit ordered and BULK if no ICE Kit on ENhanced",
        condition_attr_id=-1, condition_value="", target_attr_id=attr.entity_id,
        recommended_value="", script=_ICE_KIT_SCRIPT,
    )
    bml_eval = _fake_ice_kit_evaluator("SOME OTHER FEATURE")

    result = _hard_exclude_from_pending(
        pending, filled, display_filled, filled_source,
        con_rules=[], bml_eval=bml_eval, rec_rules=[rule],
    )

    assert result == []
    assert filled.get("packingPackageType_astro") == "BULK"


def test_package_type_resolves_when_governing_variable_never_asked_at_all():
    """The actual live bug (dev-rv-msi transcript): Package Type is
    reached in the conversation BEFORE additionalSystemEnhancementFeature
    Type_astro (order_number 120) has ever come up at all -- genuinely
    absent from `filled`, not merely empty. The real native "Recommended
    Configuration" section only ever computes once the whole form is
    submitted, by which point an untouched feature-type selection is a
    resolved "nothing selected", not a live unknown -- generically
    discovered here via bml.referenced_variables() over the rule's own
    script (no hand-maintained per-attribute variable list), and applied
    only on a local copy passed into this one check."""
    attr = _package_type_attr()
    pending = [attr]
    filled: dict = {}  # additionalSystemEnhancementFeatureType_astro never asked
    display_filled: dict = {}
    filled_source: dict = {}
    rule = RecommendationRule(
        rule_name="Default Single Pack Clamshell if ICE Kit ordered and BULK if no ICE Kit on ENhanced",
        condition_attr_id=-1, condition_value="", target_attr_id=attr.entity_id,
        recommended_value="", script=_ICE_KIT_SCRIPT,
    )
    bml_eval = _fake_ice_kit_evaluator("")

    result = _hard_exclude_from_pending(
        pending, filled, display_filled, filled_source,
        con_rules=[], bml_eval=bml_eval, rec_rules=[rule],
    )

    assert result == [], "Package Type must resolve, not be asked, even when ICE Kit was never touched"
    assert filled.get("packingPackageType_astro") == "BULK"
    assert "additionalSystemEnhancementFeatureType_astro" not in filled, (
        "the synthetic empty default must only apply to the LOCAL copy "
        "used for this one check -- the real session state must never "
        "be mutated with a value the customer never actually provided"
    )


def test_unasked_single_select_anchor_is_not_defaulted_to_empty():
    """PR #218 review (M1): "unasked -> empty" is only safe for a
    governing variable that has a real, catalog-meaningful empty state
    (e.g. a multi-select feature checklist). A decision-anchor
    single-select (Hardware Version, Country, Product) has no such
    state -- every real option is mutually exclusive, so "never asked"
    means "not yet known", not "resolved empty". Simulates this with a
    hypothetical single-select governing variable: it must NOT be
    defaulted to "", so the attribute stays in `pending` rather than
    resolving against a guessed-empty anchor."""
    attr = _package_type_attr()
    pending = [attr]
    filled: dict = {}  # the anchor variable was never asked either
    display_filled: dict = {}
    filled_source: dict = {}
    anchor_attr = ConfigAttr(
        entity_id=99, variable_name="hardwareVersion_astro", display_label="Hardware Version",
        required=True, default_value="", select_type="single",
        options=_menu("V1", "V2"),
    )
    rule = RecommendationRule(
        rule_name="anchor-based rule", condition_attr_id=-1, condition_value="",
        target_attr_id=attr.entity_id, recommended_value="",
        script='if((hardwareVersion_astro=="V1")){retVal = "BULK";}else{retVal = "SINGLE";}return retVal;',
    )

    def _fake_allowed(script, variables, cache_id=None):
        hv = variables.get("hardwareVersion_astro")
        if hv is None:
            return None
        return ["BULK"] if hv == "V1" else ["SINGLE"]

    bml_eval = BmlEvaluator({}, use_llm=False)
    bml_eval.allowed_values_for_script = _fake_allowed  # type: ignore[method-assign]

    result = _hard_exclude_from_pending(
        pending, filled, display_filled, filled_source,
        con_rules=[], bml_eval=bml_eval, rec_rules=[rule],
        all_attrs=[attr, anchor_attr],
    )

    assert result == [attr], "an unasked decision-anchor must not be treated as resolved-empty"
    assert "packingPackageType_astro" not in filled
    assert "hardwareVersion_astro" not in filled
