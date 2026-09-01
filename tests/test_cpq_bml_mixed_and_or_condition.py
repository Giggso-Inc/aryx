"""docs/CPQ_TIER1_MIXED_AND_OR_CONDITION_PARSER_PLAN_2026_08_10.md

_parse_condition requires a UNIFORM AND-only or OR-only condition chain and
returns None for anything mixed, e.g. `(A OR B OR C) AND D` -- forcing the
whole script to Tier 2, which is disabled by default (settings.bml_use_llm),
so the script permanently resolves to "unknown". Confirmed live: the real
hiding rule "Hide Frequency Bands and additional frequency band" has exactly
this shape and, despite the condition being true for the real filled state,
returned None -- meaning Frequency Bands is never hidden for APX NEXT
MULTI/XE MULTI/XN ALL as the catalog intends.

_parse_boolean_expr/_eval_boolean_expr add a separate, purely-additive
fallback: only tried when _parse_condition already failed, so every
condition it already resolves keeps using the exact same code path.
"""
from __future__ import annotations

from aryx.cpq.bml import evaluate_hide_tier1, evaluate_tier1

# The exact real script from workspace 39005's "Hide Frequency Bands and
# additional frequency band" rule.
_REAL_FREQ_BAND_HIDE_SCRIPT = (
    'if( ((productSelectionProduct_all=="APX NEXT MULTI") OR '
    '(productSelectionProduct_all=="APX NEXT XE MULTI") OR '
    '(productSelectionProduct_all=="APX NEXT XN ALL")) AND '
    '((modelSelectionbaseModel_astro<>""))){\n'
    '\treturn true;\n'
    '}\n'
    'return false;'
)


def test_real_frequency_band_script_hides_for_apx_next_multi():
    result, blocked = evaluate_hide_tier1(_REAL_FREQ_BAND_HIDE_SCRIPT, {
        "productSelectionProduct_all": "APX NEXT MULTI",
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
    })
    assert result is True
    assert blocked is False


def test_real_frequency_band_script_hides_for_xn_all_variant():
    result, blocked = evaluate_hide_tier1(_REAL_FREQ_BAND_HIDE_SCRIPT, {
        "productSelectionProduct_all": "APX NEXT XN ALL",
        "modelSelectionbaseModel_astro": "SOME_BASE_MODEL",
    })
    assert result is True


def test_real_frequency_band_script_does_not_hide_for_all_band():
    # "APX NEXT All Band" resolves to a different real code, not in the
    # OR-list -- correctly stays visible.
    result, blocked = evaluate_hide_tier1(_REAL_FREQ_BAND_HIDE_SCRIPT, {
        "productSelectionProduct_all": "APX NEXT ALL BAND",
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
    })
    assert result is False
    assert blocked is False


def test_real_frequency_band_script_unknown_when_base_model_not_yet_filled():
    result, blocked = evaluate_hide_tier1(_REAL_FREQ_BAND_HIDE_SCRIPT, {
        "productSelectionProduct_all": "APX NEXT MULTI",
    })
    assert result is None
    assert blocked is True


def test_or_of_ands_grouping():
    script = (
        'if( (a=="X" AND b=="Y") OR (c=="Z") ){\n'
        '\treturn true;\n'
        '}\n'
        'return false;'
    )
    assert evaluate_hide_tier1(script, {"a": "X", "b": "Y", "c": "no"}) == (True, False)
    assert evaluate_hide_tier1(script, {"a": "X", "b": "no", "c": "Z"}) == (True, False)
    assert evaluate_hide_tier1(script, {"a": "X", "b": "no", "c": "no"}) == (False, False)


def test_and_of_ors_short_circuits_true_or_group_despite_missing_sibling():
    # (a=="X" OR a=="Y") AND (b=="Z") -- first group already True via "a",
    # second group's variable "b" is present too, so this should resolve
    # fully; separately test the OR-group's own internal short-circuit when
    # ONE of its own comparisons references a missing variable.
    script = (
        'if( (a=="X" OR z=="never-filled") AND (b=="Z") ){\n'
        '\treturn true;\n'
        '}\n'
        'return false;'
    )
    # "a" already makes the OR-group True regardless of "z" being unknown;
    # "b" resolves the AND -- overall: True, not unknown.
    assert evaluate_hide_tier1(script, {"a": "X", "b": "Z"}) == (True, False)


def test_unparseable_mixed_condition_with_unsupported_operator_stays_none():
    # A condition BML doesn't actually use (a made-up ">=" style shape) must
    # never be guessed -- confirms the new parser still returns None (not a
    # false positive) when a leaf comparison genuinely can't be parsed.
    script = (
        'if( (a=="X" OR b=="Y") AND (c >= "5") ){\n'
        '\treturn true;\n'
        '}\n'
        'return false;'
    )
    assert evaluate_hide_tier1(script, {"a": "X", "c": "9"}) == (None, False)


def test_recommendation_value_script_with_mixed_condition():
    script = (
        'if( (region=="NA" OR region=="EU") AND (tier=="GOLD") ){\n'
        '\treturnVal = "PREMIUM";\n'
        '}\n'
        'return returnVal;'
    )
    result, blocked = evaluate_tier1(script, {"region": "EU", "tier": "GOLD"})
    assert result == ["PREMIUM"]
    assert blocked is False


def test_existing_uniform_and_chain_is_unaffected():
    # A plain, uniform AND-only chain must keep resolving via the existing
    # _parse_condition fast path -- this test exists purely to lock in "no
    # regression", not to test new code.
    script = 'if( a=="X" AND b=="Y" ){\n\treturn true;\n}\nreturn false;'
    assert evaluate_hide_tier1(script, {"a": "X", "b": "Y"}) == (True, False)
    assert evaluate_hide_tier1(script, {"a": "X", "b": "no"}) == (False, False)


def test_existing_uniform_or_chain_is_unaffected():
    script = 'if( a=="X" OR b=="Y" ){\n\treturn true;\n}\nreturn false;'
    assert evaluate_hide_tier1(script, {"a": "no", "b": "Y"}) == (True, False)
    assert evaluate_hide_tier1(script, {"a": "no", "b": "no"}) == (False, False)
