"""Tier-1 parser support for findinArray(split(VAR, "SEP"), "LITERAL")
<> -1 / == -1 -- a real, common catalog idiom (confirmed live: Package
Type's governing constraint 18131370895, plus several Duration/
Application-Services-Bundle-Duration DISALLOW rules) that the prior
parser couldn't recognize at all, since its LHS is a function call, not
a bare identifier. Every such script fell straight to Tier 2 (LLM)
regardless of whether the referenced variable was even filled --
live-confirmed root cause of a split-brain bug: the LLM's answer to
"does this array contain X" was non-deterministic across two calls in
the same turn (a real production log showed cpq_scope_match accepting a
reply that apply_answer's own separately-recomputed constrained set
then rejected).
"""
from __future__ import annotations

from aryx.cpq.bml import evaluate_tier1, referenced_variables, BmlEvaluator

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


def test_array_contains_literal_matches_the_first_branch():
    result, blocked = evaluate_tier1(
        _ICE_KIT_SCRIPT, {"additionalSystemEnhancementFeatureType_astro": "SMARTLOCATE~ICE KIT"},
    )
    assert result == ["SINGLE PACK CLAMSHELL"]
    assert blocked is False


def test_array_missing_literal_matches_the_else_branch():
    result, blocked = evaluate_tier1(
        _ICE_KIT_SCRIPT, {"additionalSystemEnhancementFeatureType_astro": "SMARTLOCATE"},
    )
    assert result == ["BULK"]
    assert blocked is False


def test_variable_present_but_empty_is_a_real_deterministic_empty_set():
    """A customer who has engaged with this multi-select and selected
    nothing (variable present as "") is NOT the same as "unknown" --
    split("", "~") deterministically can't contain the literal."""
    result, blocked = evaluate_tier1(
        _ICE_KIT_SCRIPT, {"additionalSystemEnhancementFeatureType_astro": ""},
    )
    assert result == ["BULK"]
    assert blocked is False


def test_variable_key_entirely_missing_stays_unresolvable():
    """Preserves the exact same missing-vs-empty distinction every other
    idiom in this parser already enforces -- no new guessing."""
    result, blocked = evaluate_tier1(_ICE_KIT_SCRIPT, {})
    assert result is None
    assert blocked is True


def test_not_equal_negative_one_means_array_does_not_contain():
    """The inverse idiom: findinArray(...) == -1 means "not found" --
    array does NOT contain the literal."""
    script = """
if((findinArray(split(carrierList_astro, "~"),"VERIZON") == -1)){
    retVal = "NO VERIZON";
}
else{
retVal = "HAS VERIZON";
}
return retVal;
"""
    result_no_verizon, _ = evaluate_tier1(script, {"carrierList_astro": "ATT~TMOBILE"})
    assert result_no_verizon == ["NO VERIZON"]
    result_has_verizon, _ = evaluate_tier1(script, {"carrierList_astro": "ATT~VERIZON"})
    assert result_has_verizon == ["HAS VERIZON"]


def test_array_membership_combined_with_a_plain_and_clause():
    """The idiom must also work as one clause in a uniform AND/OR chain
    (_parse_condition's flat-list path), not just standalone."""
    script = """
if((productSelectionProduct_all=="APX NEXT ENHANCED") AND (findinArray(split(additionalSystemEnhancementFeatureType_astro, "~"),"ICE KIT") <> -1)){
    retVal = "BOTH TRUE";
}
else{
retVal = "NOT BOTH";
}
return retVal;
"""
    result, _ = evaluate_tier1(script, {
        "productSelectionProduct_all": "APX NEXT ENHANCED",
        "additionalSystemEnhancementFeatureType_astro": "ICE KIT",
    })
    assert result == ["BOTH TRUE"]
    result2, _ = evaluate_tier1(script, {
        "productSelectionProduct_all": "APX NEXT XE",
        "additionalSystemEnhancementFeatureType_astro": "ICE KIT",
    })
    assert result2 == ["NOT BOTH"]


def test_real_package_type_script_no_longer_needs_tier2():
    """End-to-end: use_llm=False (Tier 2 fully disabled) still resolves
    correctly -- proving this no longer depends on the LLM/durable-cache
    path at all."""
    bml_eval = BmlEvaluator({}, use_llm=False)
    allowed = bml_eval.allowed_values_for_script(
        _ICE_KIT_SCRIPT, {"additionalSystemEnhancementFeatureType_astro": "SOME OTHER FEATURE"},
    )
    assert allowed == ["BULK"]


def test_referenced_variables_sees_the_array_membership_idiom_variable():
    """ask_api._hard_exclude_from_pending's generic "treat an entirely
    unasked governing variable as empty" fix (for the individually-vetted
    _NEVER_ASK_RECOMMENDED_ONLY_VNS attribute set only) depends on
    referenced_variables() discovering additionalSystemEnhancementFeature
    Type_astro from the raw script text -- before this fix, referenced_
    variables only recognized VAR ==/<>/!= "literal" comparisons, missing
    this variable entirely since it never appears next to a comparison
    operator (it's the first argument of split(...) instead)."""
    assert referenced_variables(_ICE_KIT_SCRIPT) == {
        "additionalSystemEnhancementFeatureType_astro",
    }
