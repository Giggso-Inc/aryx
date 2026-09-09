"""Condition parsing/evaluation for BML if-statements: single comparisons,
the findinArray array-membership idiom, and mixed AND/OR boolean trees.

Split out of `cpq/bml.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See `bml_text.py`'s docstring for the zero-patch-risk basis.
"""
from __future__ import annotations

import dataclasses
import re

from aryx.cpq.bml.bml_text import _split_top_level, _strip_wrapping_parens

# variable == "value" / variable <> "value" comparisons inside a condition.
# The RHS also accepts a bare true/false literal (variable == true), not just
# a quoted string — confirmed live: a real recommendation script gates on
# `includeASpareBatteryWithEachBodyCamera_viSoln == true` (a boolean-typed
# attr compared against a bare, unquoted literal). Without this,
# _parse_condition silently rejected the ENTIRE condition (never matched
# _CMP_RE at all), so the script's real conditional logic could never be
# evaluated deterministically — it always fell to Tier 2, which got this
# specific case wrong (returned "YES" for a customer whose spare-battery
# flag was false). Group 3 is the quoted-string RHS, group 4 the bare
# boolean RHS — callers use whichever matched.
_CMP_RE = re.compile(r'^\s*(\w+)\s*(==|<>|!=)\s*(?:"([^"]*)"|(true|false))\s*$', re.IGNORECASE)

# findinArray(split(VAR, "SEP"), "LITERAL") <> -1  /  == -1 — a genuinely
# common real-catalog idiom (confirmed live: Package Type's governing
# constraint, 18131370895, plus several Duration/Application-Services-
# Bundle-Duration DISALLOW rules use this exact shape) that _CMP_RE can't
# recognize at all, since its LHS is a function call, not a bare
# identifier. Before this, every script using this idiom fell straight to
# Tier 2 (LLM) regardless of whether the referenced variable was even
# filled — live-confirmed root cause of a real split-brain bug: the
# LLM's answer to "does this array contain X" was non-deterministic
# across two calls in the SAME turn (cpq_scope_match accepted a reply
# Tier-2 then rejected via apply_answer's own separately-recomputed
# constrained set), so a customer's exact, valid answer could be
# accepted at one layer and rejected at another.
#
# "<> -1" (findinArray returns a real index) means "the array CONTAINS
# the literal"; "== -1" (not found) means "does NOT contain it" — the
# BM-native idiom for array membership, same semantic op7/op8 already
# give multi-select declarative rule_input rows (_MULTI_SELECT_
# CONTAINS_OPERATOR/_MULTI_SELECT_NOT_CONTAINS_OPERATOR), just expressed
# as a raw script instead of a declarative row.
_ARRAY_MEMBERSHIP_RE = re.compile(
    r'^\s*find[Ii]n[Aa]rray\s*\(\s*split\s*\(\s*(\w+)\s*,\s*"([^"]*)"\s*\)\s*,\s*"([^"]*)"\s*\)'
    r'\s*(<>|==)\s*-?1\s*$',
    re.IGNORECASE,
)
# Packs (separator, literal) into _parse_condition's existing 4-tuple
# "expected" slot without changing its shape everywhere it's unpacked —
# \x1f (ASCII unit separator) can't appear in real BML string literals.
_ARRAY_PACK_SEP = "\x1f"
_ARRAY_IN_OP = "ARRAY_IN"
_ARRAY_NOT_IN_OP = "ARRAY_NOT_IN"


def _match_array_membership(cond: str) -> tuple[str, str, str] | None:
    """Match the findinArray(split(...)) idiom; returns (var, op, packed
    "sep\\x1fliteral") in the same (var, op, expected) shape _CMP_RE's
    match groups already produce, or None if this clause isn't that
    idiom at all (never a partial/guessed match)."""
    m = _ARRAY_MEMBERSHIP_RE.match(_strip_wrapping_parens(cond.strip()))
    if not m:
        return None
    var, sep, literal, arrow_op = m.groups()
    op = _ARRAY_IN_OP if arrow_op == "<>" else _ARRAY_NOT_IN_OP
    return var, op, f"{sep}{_ARRAY_PACK_SEP}{literal}"

def _array_membership_hit(actual: str, op: str, packed_expected: str) -> bool:
    """Evaluate an ARRAY_IN/ARRAY_NOT_IN clause given `actual` (the raw
    variable value, e.g. "SMARTLOCATE~ICE KIT") and the packed
    "sep\\x1fliteral" produced by _match_array_membership."""
    sep, literal = packed_expected.split(_ARRAY_PACK_SEP, 1)
    members = [p.strip() for p in actual.split(sep)] if sep else [actual.strip()]
    hit = literal.strip() in members
    return hit if op == _ARRAY_IN_OP else not hit

def _parse_condition(cond: str) -> list[tuple[str, str, str, str]] | None:
    """Parse a condition into [(joiner, var, op, value)]; None if unsupported.

    Supports single comparisons and chains joined by a uniform AND or OR,
    each optionally wrapped in its own parens. The first tuple's joiner is ''.
    """
    # Strip a redundant OUTER wrapping layer around the WHOLE chain before
    # splitting on AND/OR (2026-07-28) — live-confirmed real BML script:
    # `if( ((A) OR (B) OR ... OR (H)) ){` (a real 8-clause "Hide Housing
    # attribute if not XE model" condition). Splitting on OR first (the
    # prior order) breaks this into "((A)", "(B)", ..., "(H))" — the
    # first/last fragments are individually unbalanced, so per-fragment
    # _strip_wrapping_parens can't repair them and the whole condition was
    # silently rejected as unparseable, forcing this hiding rule to Tier-2
    # (which returns unknown when the LLM fallback is disabled, and
    # apply_hiding_rules' safe default then leaves the target VISIBLE when
    # it should have been hidden). _strip_wrapping_parens already handles
    # a genuinely-fully-wrapped string correctly (only strips when the
    # leading "(" closes at the very last character) — it just needed to
    # run on the whole cond once before the split, not only per-fragment
    # after. Safe for the existing per-clause-only-wrapped shape
    # ("(x==A) OR (y==B)", no full outer wrap) too: that shape's outer
    # "(" closes well before the string's end, so this strips nothing.
    cond = _strip_wrapping_parens(cond.strip())
    for joiner, sep in (("AND", re.compile(r'\bAND\b|&&', re.IGNORECASE)),
                        ("OR", re.compile(r'\bOR\b|\|\|', re.IGNORECASE))):
        parts = sep.split(cond)
        if len(parts) > 1:
            out = []
            for i, part in enumerate(parts):
                part_stripped = _strip_wrapping_parens(part)
                m = _CMP_RE.match(part_stripped)
                if m:
                    # group(3) is the quoted-string RHS, group(4) the bare
                    # true/false literal RHS — exactly one is populated.
                    out.append(("" if i == 0 else joiner, m.group(1), m.group(2),
                                m.group(3) if m.group(3) is not None else m.group(4)))
                    continue
                arr = _match_array_membership(part_stripped)
                if arr:
                    out.append(("" if i == 0 else joiner, arr[0], arr[1], arr[2]))
                    continue
                return None
            return out
    m = _CMP_RE.match(_strip_wrapping_parens(cond))
    if m:
        return [("", m.group(1), m.group(2),
                 m.group(3) if m.group(3) is not None else m.group(4))]
    arr = _match_array_membership(_strip_wrapping_parens(cond))
    if arr:
        return [("", arr[0], arr[1], arr[2])]
    return None

@dataclasses.dataclass
class _BoolExpr:
    """A parsed boolean expression node: "cmp" (leaf, a single comparison)
    or "and"/"or" (internal, `parts` are child _BoolExpr nodes)."""

    kind: str
    parts: list["_BoolExpr"] | None = None
    var: str | None = None
    op: str | None = None
    value: str | None = None


_TOP_LEVEL_OR_RE = re.compile(r'\bOR\b|\|\|', re.IGNORECASE)
_TOP_LEVEL_AND_RE = re.compile(r'\bAND\b|&&', re.IGNORECASE)

def _parse_boolean_expr(cond: str) -> "_BoolExpr | None":
    """Recursive-descent parser for a mixed AND/OR condition, standard
    precedence (AND binds tighter than OR — matches how every real mixed
    script found in the live catalog survey is actually written). Returns
    None if any part doesn't reduce to a single comparison or a further
    AND/OR split — never guesses a shape it can't fully account for."""
    cond = cond.strip()
    while True:
        # _strip_wrapping_parens only removes ONE layer per call — the real
        # "Hide Frequency Bands..." script's second AND-part is DOUBLE-
        # wrapped (`((modelSelectionbaseModel_astro<>""))`), confirmed live.
        # Loop to stability so a leftover single layer doesn't make the
        # final _CMP_RE match fail (it anchors on a leading word character,
        # not "(").
        stripped = _strip_wrapping_parens(cond)
        if stripped == cond:
            break
        cond = stripped
    or_parts = _split_top_level(cond, _TOP_LEVEL_OR_RE)
    if or_parts is not None:
        parsed = [_parse_boolean_expr(p) for p in or_parts]
        if any(p is None for p in parsed):
            return None
        return _BoolExpr(kind="or", parts=parsed)
    and_parts = _split_top_level(cond, _TOP_LEVEL_AND_RE)
    if and_parts is not None:
        parsed = [_parse_boolean_expr(p) for p in and_parts]
        if any(p is None for p in parsed):
            return None
        return _BoolExpr(kind="and", parts=parsed)
    m = _CMP_RE.match(cond)
    if m:
        return _BoolExpr(
            kind="cmp", var=m.group(1), op=m.group(2),
            value=m.group(3) if m.group(3) is not None else m.group(4),
        )
    arr = _match_array_membership(cond)
    if arr:
        var, op, packed = arr
        return _BoolExpr(kind="cmp", var=var, op=op, value=packed)
    return None

def _eval_boolean_expr(expr: "_BoolExpr", variables: dict[str, str]) -> tuple[bool | None, bool]:
    """Recursively evaluate a _BoolExpr. Returns (result, blocked_by_missing_
    var) — same per-condition contract _first_matching_branch's flat-chain
    evaluation already uses, generalized to nesting. Short-circuits the same
    way: an "or" node with any confirmed-True child is True regardless of a
    sibling's missing variable; symmetrically an "and" node with any
    confirmed-False child is False regardless of a sibling's missing
    variable. Only genuinely undetermined when nothing short-circuits AND
    something is missing."""
    if expr.kind == "cmp":
        actual = variables.get(expr.var)
        if actual is None:
            return None, True
        if expr.op in (_ARRAY_IN_OP, _ARRAY_NOT_IN_OP):
            return _array_membership_hit(actual, expr.op, expr.value or ""), False
        hit = actual.strip().lower() == (expr.value or "").strip().lower()
        if expr.op in ("<>", "!="):
            hit = not hit
        return hit, False

    child_results: list[bool | None] = []
    any_missing = False
    for part in expr.parts or []:
        result, missing = _eval_boolean_expr(part, variables)
        if missing:
            any_missing = True
        child_results.append(result)

    if expr.kind == "or":
        if any(r is True for r in child_results):
            return True, False
        if any_missing:
            return None, True
        return False, False
    # "and"
    if any(r is False for r in child_results):
        return False, False
    if any_missing:
        return None, True
    return True, False
