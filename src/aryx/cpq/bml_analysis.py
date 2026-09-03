"""Best-effort script analysis: referenced-variable scanning, literal
comparison harvesting, and the array-iteration idiom recognizer.

Split out of `cpq/bml.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See `bml_text.py`'s docstring for the zero-patch-risk basis.
"""
from __future__ import annotations

import dataclasses
import re

from aryx.cpq.bml_text import _find_block


def referenced_variables(script: str) -> set[str]:
    """Variable names compared in the script (Tier-1 scan, best effort).

    Live-verified gap (2026-07-24): only matched a quoted-string RHS
    (`var == "X"`), missing bare boolean literal comparisons (`var ==
    true`) entirely — the exact same idiom `_CMP_RE` in evaluate_tier1
    already had to learn to parse (bare booleans are common, e.g. "if
    (spareBattery == true)"). Since this function's result scopes
    allowed_values_for_script's cache key (BmlEvaluator._SHARED_SCRIPT_
    CACHE), missing a variable here means the cache key never varies
    with that variable's value — the FIRST-ever evaluation's result gets
    reused for every later call regardless of what that variable's
    current value actually is, a much worse bug than a cache miss.

    Regression caught in review (PR #117): the first attempt at this fix
    put a trailing `\b` after the WHOLE alternation, including the
    quoted-string branch — a word boundary can never match right after a
    closing `"`, so it silently broke the far more common quoted-string
    case (`var == "X"` matched nothing at all). The `\b` belongs only on
    the bare boolean literals, to stop them matching as a substring of a
    longer identifier (e.g. "truely") — it must not apply to the
    quoted-string alternative at all.
    """
    found = {
        m.group(1) for m in re.finditer(
            r'(\w+)\s*(?:==|<>|!=)\s*(?:"[^"]*"|true\b|false\b)', script, re.IGNORECASE)
    }
    # findinArray(split(VAR, "SEP"), "LITERAL") -- the same real-catalog
    # array-membership idiom evaluate_tier1 gained native support for
    # (see _ARRAY_MEMBERSHIP_RE). The comparison-based regex above can't
    # see VAR here since it never appears next to ==/<>/!=; missing it
    # here means allowed_values_for_script's cache key never varies with
    # this variable's value -- the same stale-cache risk this function's
    # own docstring already documents for the comparison idiom.
    found |= {
        m.group(1) for m in re.finditer(
            r'find[Ii]n[Aa]rray\s*\(\s*split\s*\(\s*(\w+)\s*,', script, re.IGNORECASE)
    }
    return found

_VAR_VALUE_RE = re.compile(r'(\w+)\s*(?:==|<>|!=)\s*"([^"]*)"')


def extract_literal_comparisons(script: str) -> list[tuple[str, str]]:
    """Every (variable, literal_value) pair compared anywhere in a script.

    A broad regex scan, NOT gated on the script being fully Tier-1
    parseable (unlike evaluate_tier1/evaluate_hide_tier1's stricter
    if/else-chain grammar) — used only to harvest candidate keywords a
    script cares about for a given variable (e.g. customerType=="FEDERAL"),
    not to execute the script's logic. Confirmed live only ~6 of 119
    real script-backed hiding rules fit the stricter Tier-1 grammar, but
    the literal values they compare against are readable from ALL of them
    via this simpler scan — no reason to limit keyword discovery to the
    fully-executable subset.
    """
    return [(m.group(1), m.group(2)) for m in _VAR_VALUE_RE.finditer(script)]

# Array-iteration idiom recognizer (docs/CPQ_BML_ARRAY_ITERATION_TIER_PLAN.md):
#   arrayRange = range(mountingArrayControl_viSoln);
#   for idx in arrayRange {
#       if(mountingTypeArray_viSoln[idx]=="Shirt Magnetic Mount"
#          AND mountingTypeArrayqty_viSoln[idx]>0)
#       { val=true; }
#   }
#   return val;
# Confirmed present across all 3 available catalog exports (SVX, APX
# NEXT/DM4400, SL3500e) — loop-variable name differs per script (idx, cnt,
# each, cntEach, i, k), which these patterns are agnostic to by design
# (they capture whatever identifier each script itself uses).
_ARRAY_RANGE_RE = re.compile(r'(\w+)\s*=\s*range\(\s*(\w+)\s*\)\s*;', re.IGNORECASE)
_ARRAY_LOOP_RE = re.compile(r'for\s+(\w+)\s+in\s+(\w+)\s*\{', re.IGNORECASE)
_ARRAY_IF_RE = re.compile(
    r'if\s*\(\s*(\w+)\[(\w+)\]\s*==\s*"([^"]*)"'
    r'(?:\s*AND\s*(\w+)\[(\w+)\]\s*>\s*(\d+))?\s*\)\s*\{',
    re.IGNORECASE,
)
_ARRAY_SUBSCRIPT_RE = re.compile(r'(\w+)\[(\w+)\]')


@dataclasses.dataclass(frozen=True)
class ArrayIterationShape:
    """Structural facts recognized from the array-iteration BML idiom —
    which array-control attr is ranged over, which selector array is
    compared against a literal, and (when present) which parallel quantity
    array is cross-referenced.

    This captures STRUCTURE only (the attribute names involved), not
    semantics — evaluating the recognized shape against live session state
    is a separate, not-yet-built runtime tier (see the plan doc's
    Approach A). Approach B (ingestion-time graph enrichment, what this
    recognizer currently serves) only needs to know which attrs a script's
    array-iteration reads.
    """
    control_attr: str
    selector_attr: str
    literal_value: str
    qty_attr: str | None


def parse_array_iteration(script: str) -> ArrayIterationShape | None:
    """Recognize `<rangevar> = range(<control_attr>); for <idx> in
    <rangevar> { if(<selector>[<idx>]=="<value>" (AND <qty>[<idx>]><n>)?)
    { ... } }` — the array-iteration idiom described above.

    Same "structural match or bail, never partial-guess" discipline as
    Tier 1's own branch parser: anything not fitting this exact shape
    (different idiom, dictionary/string-splitting logic inside the loop
    body, etc.) returns None rather than a best-effort guess.

    The quantity attr is read either from the condition's own `AND
    qty[idx]>n` clause, or — for the "quantity-copy" variant with no such
    clause — from a subscripted reference to a DIFFERENT array using the
    same loop variable inside the if-body (e.g. `val=qty[idx];` or a bare
    `return qty[idx];`).
    """
    if not script:
        return None
    range_m = _ARRAY_RANGE_RE.search(script)
    if not range_m:
        return None
    range_var, control_attr = range_m.group(1), range_m.group(2)

    loop_m = _ARRAY_LOOP_RE.search(script, range_m.end())
    if not loop_m or loop_m.group(2) != range_var:
        return None
    loop_var = loop_m.group(1)

    loop_block = _find_block(script, loop_m.end() - 1)
    if not loop_block:
        return None
    loop_body, _after_loop = loop_block

    if_m = _ARRAY_IF_RE.search(loop_body)
    if not if_m:
        return None
    selector_attr, sel_idx, literal_value = if_m.group(1), if_m.group(2), if_m.group(3)
    if sel_idx != loop_var:
        return None

    qty_attr = None
    if if_m.group(4):
        cond_qty_attr, qty_idx = if_m.group(4), if_m.group(5)
        if qty_idx == loop_var:
            qty_attr = cond_qty_attr

    if_block = _find_block(loop_body, if_m.end() - 1)
    if not if_block:
        return None
    if_body, _after_if = if_block

    if qty_attr is None:
        # Quantity-copy variant — no threshold check in the condition, but
        # the if-body itself subscripts a (different) array by the same
        # loop var; that's the quantity attr being read.
        for sub_m in _ARRAY_SUBSCRIPT_RE.finditer(if_body):
            if sub_m.group(2) == loop_var and sub_m.group(1) != selector_attr:
                qty_attr = sub_m.group(1)
                break

    return ArrayIterationShape(
        control_attr=control_attr,
        selector_attr=selector_attr,
        literal_value=literal_value,
        qty_attr=qty_attr,
    )
