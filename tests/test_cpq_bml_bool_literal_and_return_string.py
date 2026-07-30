"""Regression coverage for two related Tier-1 BML gaps found live on SVX's
real "Set defaults for VX650" recommendation script:

    if (includeASpareBatteryWithEachBodyCamera_viSoln == true) {
        return "YES";
    }
    return "";

1. `_CMP_RE` only matched comparisons against a QUOTED string literal
   (`var == "value"`), never a bare boolean literal (`var == true`) — a
   very common BML idiom for boolean-typed attrs. The condition above
   never matched at all, so `_parse_condition` (and everything built on
   it) silently rejected the script's entire conditional logic.

2. `_branch_values` only recognized `returnVal = "A"|"B";` assignments,
   never a direct `return "literal";` inside a branch body — this script
   uses the latter.

Together these meant the script could never be evaluated deterministically
by Tier 1 at all (always fell through to Tier 2/unknown) — and the live
LLM Tier-2 call for this exact script returned "YES" even when the real
gating variable was false, silently forcing a battery-subscription
recommendation onto a customer whose spare-battery flag was false.
"""
from __future__ import annotations

from aryx.cpq.bml import evaluate_tier1, _parse_branches, _parse_condition, _branch_values

_RESTRICT_SERVICE_TYPE_SCRIPT = (
    'if(archeType_viSoln=="CAPEX PURCHASE"){\n\n'
    'return "1 YEAR STANDARD WARRANTY ONLY|^|Essential Support Software and Hardware Repair'
    '|^|Essential with Accidental Damage and Advanced Replacement";\n'
    '}\n'
    'elif(archeType_viSoln=="HARDWARE AS A SERVICE"){\n\n'
    'return "ESSENTIAL WITH ACCIDENTAL DAMAGE AND ADVANCED REPLACEMENT HAAS";\n'
    '}\n'
    'else\n{\n\n'
    'return "";\n'
    '}'
)

_REAL_SCRIPT = (
    'if( (includeASpareBatteryWithEachBodyCamera_viSoln == true)){\n'
    '\treturn "YES";\n'
    '}\n'
    'return "";'
)


def test_bare_boolean_literal_condition_parses():
    cond = _parse_condition("includeASpareBatteryWithEachBodyCamera_viSoln == true")
    assert cond == [("", "includeASpareBatteryWithEachBodyCamera_viSoln", "==", "true")]


def test_bare_boolean_literal_condition_still_supports_quoted_strings():
    cond = _parse_condition('hWVersion_astro == "NEXT ENHANCED LTE PLUS 5G"')
    assert cond == [("", "hWVersion_astro", "==", "NEXT ENHANCED LTE PLUS 5G")]


def test_real_script_branches_are_parseable():
    assert _parse_branches(_REAL_SCRIPT) is not None


def test_real_script_returns_yes_when_condition_true():
    allowed, blocked = evaluate_tier1(
        _REAL_SCRIPT, {"includeASpareBatteryWithEachBodyCamera_viSoln": "true"})
    assert blocked is False
    assert allowed == ["YES"]


def test_real_script_does_not_force_yes_when_condition_false():
    # Confirmed live bug: with the gating variable false, this script
    # (via the old LLM-only Tier-2 fallback) incorrectly resolved to
    # "YES" anyway. Deterministic Tier 1 must now correctly find no
    # matching branch (condition false, no else) and yield None — the
    # caller (apply_recommendation_rules) treats this as "no
    # recommendation", never forcing a value.
    allowed, blocked = evaluate_tier1(
        _REAL_SCRIPT, {"includeASpareBatteryWithEachBodyCamera_viSoln": "false"})
    assert blocked is False
    assert allowed is None


def test_real_script_is_blocked_when_variable_unfilled():
    allowed, blocked = evaluate_tier1(_REAL_SCRIPT, {})
    assert blocked is True
    assert allowed is None


def test_branch_values_resolves_direct_return_string_literal():
    assert _branch_values('\treturn "YES";\n') == ["YES"]


def test_branch_values_return_empty_string_yields_empty_list_not_none():
    assert _branch_values('return "";') == []


def test_branch_values_rejects_concatenated_return_string():
    body = 'return "A"+variable+"B";'
    assert _branch_values(body) is None


def test_branch_values_splits_pipe_caret_delimited_return_string():
    # Real SVX "Restrict Service Type Based on the Solution Type" script —
    # confirmed live: this `|^|`-packed single-quote return collapsed into
    # ONE bogus concatenated "value" that never matched any real
    # item_value, corrupting Service Type resolution for every
    # CapEx-purchase quote.
    body = (
        'return "1 YEAR STANDARD WARRANTY ONLY|^|Essential Support Software and Hardware Repair'
        '|^|Essential with Accidental Damage and Advanced Replacement";'
    )
    assert _branch_values(body) == [
        "1 YEAR STANDARD WARRANTY ONLY",
        "Essential Support Software and Hardware Repair",
        "Essential with Accidental Damage and Advanced Replacement",
    ]


def test_branch_values_splits_pipe_caret_delimited_returnval_assignment():
    # Same `|^|` idiom, via the returnVal= assignment path instead of a
    # bare return statement — confirmed live in real APX NEXT scripts
    # (docs/CPQ_APX_NEXT_RULE_CATALOG.md).
    body = 'retVal ="SMARTMESSAGING|^|VIQI VIRTUAL PARTNER|^|SMARTINCIDENT";'
    assert _branch_values(body) == ["SMARTMESSAGING", "VIQI VIRTUAL PARTNER", "SMARTINCIDENT"]


def test_assign_re_matches_retval_without_urn():
    # _ASSIGN_RE previously required the literal substring "return", which
    # "retVal" (no "urn") doesn't contain at all — confirmed live: real APX
    # NEXT scripts use "retVal"/"retval" interchangeably with "returnVal".
    assert _branch_values('retVal = "A"|"B";') == ["A", "B"]
    assert _branch_values('retval = "A"|"B";') == ["A", "B"]


def test_restrict_service_type_script_resolves_correctly_for_capex_purchase():
    # End-to-end: the real script, parsed and evaluated exactly as it
    # would be for a live CapEx-purchase SVX quote. Confirmed live this
    # previously either failed to parse (falling to a non-deterministic
    # Tier-2 LLM call) or — after the return-string fix alone, before the
    # |^| split fix — collapsed to one bogus concatenated allowed value.
    allowed, blocked = evaluate_tier1(
        _RESTRICT_SERVICE_TYPE_SCRIPT, {"archeType_viSoln": "CAPEX PURCHASE"})
    assert blocked is False
    assert allowed == [
        "1 YEAR STANDARD WARRANTY ONLY",
        "Essential Support Software and Hardware Repair",
        "Essential with Accidental Damage and Advanced Replacement",
    ]


# docs/config_consistency_issues_2026-07-30.md issue 2 follow-up — real
# APX Next scripts build a |^|-delimited allowed-list via string
# CONCATENATION instead of one packed literal, e.g.
# `retVal = "CORE BUNDLE" + "|^|" + "SECURITY BUNDLE" + "|^|" + ...;` —
# a fully-literal chain (no variables) that's genuinely resolvable, but
# previously bailed as "unparseable" the same as a real dynamic
# concatenation would, and paid an unnecessary Tier-2 LLM call every time.

def test_branch_values_resolves_literal_concatenated_pipe_caret_list():
    body = (
        'retVal = "CORE BUNDLE" + "|^|" + "SECURITY BUNDLE"+ "|^|" '
        '+ "OPERATIONAL ASSURANCE BUNDLE" + "|^|" + "TACTICAL BUNDLE";'
    )
    assert _branch_values(body) == [
        "CORE BUNDLE", "SECURITY BUNDLE", "OPERATIONAL ASSURANCE BUNDLE", "TACTICAL BUNDLE",
    ]


def test_branch_values_resolves_literal_concatenated_return_string():
    body = 'return "A" + "|^|" + "B" + "|^|" + "C";'
    assert _branch_values(body) == ["A", "B", "C"]


def test_branch_values_still_rejects_a_real_variable_in_the_chain():
    # The ORIGINAL guard this fix sits next to (SVX HTML-building case) —
    # a genuine variable mixed into the concatenation is NOT statically
    # resolvable and must stay rejected, never guessed at.
    assert _branch_values('retVal = "A" + link + "B";') is None
    assert _branch_values('return "A" + link + "B";') is None


def test_branch_values_rejects_a_function_call_in_the_chain():
    assert _branch_values('retVal = "A" + someFunc() + "B";') is None
