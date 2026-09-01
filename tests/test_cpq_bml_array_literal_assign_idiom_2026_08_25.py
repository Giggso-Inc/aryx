"""Tier-1 support for the `VAR = string[]{"A","B","C"};` array-literal
assignment idiom, returned by reference elsewhere in the script.

Live-verified gap, 2026-08-25 (SVX Mounting Type (Array)): the real
narrowing rule's script declares `ret = string[];` up front, reassigns
`ret` to a comma-separated `string[]{...}` literal inside each if/else
branch, then does `return ret;` OUTSIDE the if/else entirely.
`_parse_branches` only ever hands `_branch_values` the matched branch's
OWN `{...}` body — the trailing `return ret;` is never part of it — so
this idiom needs its own recognizer, distinct from `_ASSIGN_RE`'s
pipe-delimited `returnVal = "A"|"B"` shape (different variable name,
different literal syntax, no `return` keyword in the branch body at
all). Before this fix, `evaluate_tier1` returned `(None, False)` for
this exact real script even though its condition parsed and matched
correctly — Tier 2 (LLM) then also failed to resolve it live, leaving
the customer-facing option list at the raw, unfiltered 12-option
catalog menu instead of the narrowed 5/6 the rule was authored to
produce.
"""
from __future__ import annotations

from aryx.cpq.bml import evaluate_tier1, _branch_values

_REAL_MOUNTING_TYPE_SCRIPT = (
    'ret = string[];\n'
    '//if (customerType == "FEDERAL"){  removed for PO-153005\n'
    'if ((modelSelectionSelectModel_viSoln == "SVX VIDEO REMOTE SPEAKER MIC UL") OR '
    '(modelSelectionSelectModel_viSoln == "SVX VIDEO RSM TAA")) {  //Added for PO-153005\n'
    '\tret = string[]{"Shirt Magnetic Mount","Jacket Magnetic Mount","Shirt Mount",'
    '"Jacket Clip Mount","Locking Molle Mount","TEK-LOK Belt Mount"};\n'
    '} else {\n'
    '\tret = string[]{"Shirt Magnetic Mount","Jacket Magnetic Mount","Shirt Mount",'
    '"Jacket Clip Mount","Locking Molle Mount"};\n'
    '}\n'
    'return ret;'
)


def test_branch_values_extracts_array_literal_regardless_of_variable_name():
    assert _branch_values('ret = string[]{"A","B","C"};') == ["A", "B", "C"]
    assert _branch_values('retVal = string[]{"A","B"};') == ["A", "B"]
    assert _branch_values('someOtherName = string[]{"X"};') == ["X"]


def test_branch_values_handles_no_space_before_brackets():
    assert _branch_values('ret = string[] {"A", "B"};') == ["A", "B"]


def test_branch_values_takes_the_last_assignment_when_body_has_several():
    """Raven review (PR #269, finding: "first-match-wins ambiguity, no
    target-variable check"): the branch's own trailing `return VAR;` is
    never part of `body` at all (see _parse_branches), so which
    assignment "counts" can't be resolved by variable name. A scratch/
    debug assignment set before the real return-carrying one must not
    win — matches `_LOCAL_LITERAL_ASSIGN_RE`'s own last-wins precedent
    for this exact ambiguity class (evaluate_constant_return)."""
    body = 'tempDebug = string[]{"UNUSED_DEBUG_VALUE"};\nret = string[]{"A","B","C"};'
    assert _branch_values(body) == ["A", "B", "C"]


def test_real_mounting_type_script_resolves_the_else_branch():
    allowed, blocked = evaluate_tier1(
        _REAL_MOUNTING_TYPE_SCRIPT,
        {"modelSelectionSelectModel_viSoln": "SVX Video Remote Speaker Mic"},
    )
    assert blocked is False
    assert allowed == [
        "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Mount",
        "Jacket Clip Mount", "Locking Molle Mount",
    ]


def test_real_mounting_type_script_resolves_the_if_branch():
    allowed, blocked = evaluate_tier1(
        _REAL_MOUNTING_TYPE_SCRIPT,
        {"modelSelectionSelectModel_viSoln": "SVX VIDEO REMOTE SPEAKER MIC UL"},
    )
    assert blocked is False
    assert allowed == [
        "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Mount",
        "Jacket Clip Mount", "Locking Molle Mount", "TEK-LOK Belt Mount",
    ]


def test_real_mounting_type_script_blocked_when_model_unfilled():
    allowed, blocked = evaluate_tier1(_REAL_MOUNTING_TYPE_SCRIPT, {})
    assert allowed is None
    assert blocked is True
