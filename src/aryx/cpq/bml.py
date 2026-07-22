"""BML (BigMachines Markup Language) rule-script evaluation.

CPQ rules whose logic lives in a BmFunction script (condition_function_id or
action function_id != -1) were previously dropped by the rule loaders, making
the engine blind to constraints like "restrict allowed hardware by radio
frequency" — the exact class of rule that produces illegal configurations
when ignored.

Two evaluation tiers:

Tier 1 — deterministic mini-evaluator for the dominant BML idiom::

    if (hWVersion_astro == "NEXT ENHANCED LTE PLUS 5G") {
        returnVal = "APX NEXT ENHANCED"|"APX NEXT XE 4G LTE PLUS 5G";
    } else {
        returnVal = "APX NEXT INTL FED"|"APX NEXT XN SINGLE BAND";
    }
    return returnVal;

    An if/else-if/else chain of equality comparisons on variable names,
    each branch assigning a pipe-delimited list of allowed values.

Tier 2 — LLM fallback: scripts Tier 1 cannot parse are handed to the reason
model (ARYX_LLM_REASON_MODEL, role="answer") with the current variable
state; the reply is a JSON allowed-values list. Results are cached per
(script, relevant-variable-state).

Both tiers return ``None`` when the outcome is unknown (unparseable script,
referenced variable not yet filled, LLM unavailable) — the caller treats
None as "no constraint derived", never as "everything allowed".
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re

from aryx.cpq.logging_context import install_run_id_logging

logger = logging.getLogger(__name__)
install_run_id_logging(__name__)

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

# returnVal = "A"|"B"|... assignment inside a branch body. Also matches
# `retVal = ...` (no "urn") — confirmed live: dozens of real APX NEXT
# constraint/recommendation scripts (docs/CPQ_APX_NEXT_RULE_CATALOG.md) use
# "retVal" interchangeably with "returnVal"; the old pattern required the
# literal substring "return", which "retVal" doesn't contain at all, so
# every such script silently fell through to Tier 2 instead of Tier 1.
_ASSIGN_RE = re.compile(r're(?:t|turn)[Vv]al\s*=\s*((?:"[^"]*"\s*(?:\|\s*)?)+);?')
_STR_RE = re.compile(r'"([^"]*)"')

# return "literal"; directly inside a branch body — a different idiom from
# the returnVal assignment above. Confirmed live: the same recommendation
# script above returns "YES" (or "" outside any branch) as a literal
# string, never assigning to returnVal at all.
_RETURN_STR_RE = re.compile(r'\breturn\s+"([^"]*)"\s*;?')

# if (...) { ... } chain scanner
_IF_RE = re.compile(r'\bif\s*\(', re.IGNORECASE)

# Constructs that put a script beyond Tier 1 (function calls, nesting hints).
_TIER1_BLOCKERS = re.compile(
    r'\b(for|while|foreach|util\.|usersessionget|jsonarray|dict\(|urldata)\b',
    re.IGNORECASE,
)


def _strip_line_comments(text: str) -> str:
    """Strip `// ...` line comments, but never inside a quoted string
    literal (a `"http://..."` value must survive intact).

    Every Tier-1 regex scanner (`_ASSIGN_RE`, `_BOOL_RETURN_RE`, `_IF_RE`,
    `_CMP_RE` via _parse_condition) previously scanned the RAW script text,
    including comments — so an author's own commented-out scratch line
    (e.g. `//returnVal = "APX NEXT Enhanced";`) matched BEFORE the real,
    live statement right after it (`returnVal = "APX NEXT ENHANCED";`),
    confirmed live: a real "Default APX Next Enhanced based on HW version"
    recommendation script returned the commented-out (wrong-cased) string
    instead of its actual executed assignment. _parse_branches strips
    comments once at entry so every downstream scan (bodies/conditions
    sliced from that same text) sees comment-free source.
    """
    out: list[str] = []
    in_str = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            if j == -1:
                break
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _find_block(text: str, open_idx: int) -> tuple[str, int] | None:
    """Return (block_body, index_after_close) for the {...} starting at open_idx."""
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1:i], i + 1
    return None


def _strip_wrapping_parens(text: str) -> str:
    """Strip one layer of enclosing parens, e.g. `(a=="b")` -> `a=="b"`, but
    only when the leading `(` closes at the very end (not e.g. `(a) OR (b)`
    sliced mid-way, which must be left alone). Real BML condition chains
    commonly wrap every clause in its own parens
    (`(x=="A") OR (y=="B")`) — confirmed live in a real hiding-rule
    script — which the bare _CMP_RE anchor match would otherwise reject."""
    text = text.strip()
    if not (text.startswith("(") and text.endswith(")")):
        return text
    depth = 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text if i != len(text) - 1 else text[1:-1].strip()
    return text


def _parse_condition(cond: str) -> list[tuple[str, str, str, str]] | None:
    """Parse a condition into [(joiner, var, op, value)]; None if unsupported.

    Supports single comparisons and chains joined by a uniform AND or OR,
    each optionally wrapped in its own parens. The first tuple's joiner is ''.
    """
    cond = cond.strip()
    for joiner, sep in (("AND", re.compile(r'\bAND\b|&&', re.IGNORECASE)),
                        ("OR", re.compile(r'\bOR\b|\|\|', re.IGNORECASE))):
        parts = sep.split(cond)
        if len(parts) > 1:
            out = []
            for i, part in enumerate(parts):
                m = _CMP_RE.match(_strip_wrapping_parens(part))
                if not m:
                    return None
                # group(3) is the quoted-string RHS, group(4) the bare
                # true/false literal RHS — exactly one is populated.
                out.append(("" if i == 0 else joiner, m.group(1), m.group(2),
                            m.group(3) if m.group(3) is not None else m.group(4)))
            return out
    m = _CMP_RE.match(_strip_wrapping_parens(cond))
    if m:
        return [("", m.group(1), m.group(2),
                 m.group(3) if m.group(3) is not None else m.group(4))]
    return None


def _parse_branches(script: str) -> list[tuple[list | None, str]] | None:
    """Parse an if / else-if / else chain into [(condition, body)].

    condition is the _parse_condition output, or None for the else branch.
    Returns None when the script doesn't fit the Tier-1 idiom.
    """
    script = _strip_line_comments(script)
    if _TIER1_BLOCKERS.search(script):
        return None
    branches: list[tuple[list | None, str]] = []
    m = _IF_RE.search(script)
    if not m:
        return None
    pos = m.start()
    text = script
    while True:
        m = _IF_RE.search(text, pos)
        if not m:
            break
        paren_start = m.end() - 1
        depth, cond_end = 0, -1
        for i in range(paren_start, len(text)):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    cond_end = i
                    break
        if cond_end == -1:
            return None
        cond = _parse_condition(text[paren_start + 1:cond_end])
        if cond is None:
            return None
        brace = text.find("{", cond_end)
        if brace == -1:
            return None
        block = _find_block(text, brace)
        if block is None:
            return None
        body, after = block
        if _IF_RE.search(body):
            return None  # nested if → Tier 2
        branches.append((cond, body))
        # else / else if?
        rest = text[after:].lstrip()
        if rest.lower().startswith("else"):
            rest2 = rest[4:].lstrip()
            if rest2.lower().startswith("if"):
                pos = text.find("if", after)
                continue
            brace2 = text.find("{", after)
            if brace2 == -1:
                return None
            block2 = _find_block(text, brace2)
            if block2 is None:
                return None
            body2, _ = block2
            if _IF_RE.search(body2):
                return None
            branches.append((None, body2))
            break
        break
    return branches or None


def _split_pipe_caret_values(values: list[str]) -> list[str]:
    """Expand any `A|^|B|^|C`-shaped entry into separate values.

    `|^|` is a real, common BM delimiter for a multi-value allowed-list
    packed inside a SINGLE quoted string (confirmed live: dozens of real
    APX NEXT/SVX constraint/recommendation scripts —
    docs/CPQ_APX_NEXT_RULE_CATALOG.md — e.g. `retVal =
    "SMARTMESSAGING|^|VIQI VIRTUAL PARTNER|^|SMARTINCIDENT";`) — a
    different convention from the `"A"|"B"` multi-QUOTE pipe format
    `_ASSIGN_RE` otherwise splits on. Without this, a single `|^|`-packed
    quoted string collapsed into ONE bogus concatenated "value" that never
    matches any real item_value — confirmed live: "Restrict Service Type
    Based on the Solution Type" corrupted Service Type resolution for
    every CapEx-purchase SVX quote this way.
    """
    out: list[str] = []
    for v in values:
        if "|^|" in v:
            out.extend(part.strip() for part in v.split("|^|") if part.strip())
        elif v:
            out.append(v)
    return out


def _branch_values(body: str) -> list[str] | None:
    """Extract the pipe-delimited allowed-value list from a branch body.

    Returns None (unparseable — caller falls through to Tier 2/unknown,
    never a guess) when the assignment's right-hand side continues past
    the pipe-delimited literal list `_ASSIGN_RE` captures — e.g. string
    concatenation (`+`). Without this check, a real SVX script

        returnval ="<model style="+"\\""+"color:#2B8838;..."+link+"</b></model>";

    silently matched only its FIRST quoted fragment (`"<model style="`)
    and returned that truncated garbage as if it were the whole,
    intentional value (confirmed live: sVXTAAKitHelpText_viSoln's real
    payload value was the literal truncated string `<model style=`).
    `_ASSIGN_RE`'s own alternation only accepts `"literal"` segments
    joined by `|`, so it stops matching (without erroring) at the first
    `+` — this check catches exactly that silent truncation.
    """
    m = _ASSIGN_RE.search(body)
    if not m:
        # A DIFFERENT idiom from the returnVal assignment above — some
        # real scripts `return "literal";` directly (confirmed live: SVX's
        # "Set defaults for VX650" — `if (spareBattery == true) { return
        # "YES"; }`). Same concatenation guard as the returnVal path: a
        # tail continuing with `+` past the matched literal means this
        # isn't a clean single-value return, so bail rather than truncate.
        m2 = _RETURN_STR_RE.search(body)
        if not m2:
            return None
        tail2 = body[m2.end():].lstrip()
        if tail2.startswith("+"):
            logger.warning(
                "cpq: Tier-1 _branch_values found a `return \"...\";` whose "
                "value continues past the matched literal (string "
                "concatenation) — treating as unparseable rather than "
                "returning a truncated value. matched=%r body=%.200r",
                m2.group(0), body,
            )
            return None
        value = m2.group(1)
        return _split_pipe_caret_values([value]) if value else []
    tail = body[m.end():].lstrip()
    if tail.startswith("+"):
        # WARNING, not info — this deployment's root logger is configured
        # at WARNING (confirmed live: aryx.cpq.bml's effective level was
        # WARNING, silently dropping an earlier INFO call here), and this
        # signals a real BML script shape the evaluator can't safely
        # resolve — worth surfacing, not just informational chatter.
        logger.warning(
            "cpq: Tier-1 _branch_values found a returnVal assignment "
            "whose right-hand side continues past the pipe-delimited "
            "literal list (string concatenation) — treating as "
            "unparseable rather than returning a truncated value. "
            "matched=%r body=%.200r", m.group(0), body,
        )
        return None
    values = [v.strip() for v in _STR_RE.findall(m.group(1))]
    return _split_pipe_caret_values([v for v in values if v and v != "|"])


# `return true;` / `return false;` inside a hiding-rule branch body — a
# different idiom from constraints' `returnVal = "A"|"B"` (see
# _branch_values). Confirmed live against a real rule ("Hide HW Version
# unless APX Next NA or APX Next fed model (portables)"):
#     if (modelSelectionRegion_astro=="NA" OR ...) { return false; }
#     else { return true; }
_BOOL_RETURN_RE = re.compile(r'\breturn\s+(true|false)\b', re.IGNORECASE)


def _branch_bool(body: str) -> bool | None:
    """Extract a literal true/false from a hide/show branch body."""
    m = _BOOL_RETURN_RE.search(body)
    if not m:
        return None
    return m.group(1).lower() == "true"


def referenced_variables(script: str) -> set[str]:
    """Variable names compared in the script (Tier-1 scan, best effort)."""
    return {m.group(1) for m in re.finditer(r'(\w+)\s*(?:==|<>|!=)\s*"', script)}


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


def _first_matching_branch(
    script: str, variables: dict[str, str],
) -> tuple[str | None, bool]:
    """Walk a Tier-1 if/else-if/else chain and return the first matching
    branch's raw body text (or None), plus blocked_by_missing_var.

    Shared by evaluate_tier1 (constraint/recommendation scripts, whose
    bodies are a `returnVal = "A"|"B"` allowed-value assignment) and
    evaluate_hide_tier1 (hiding scripts, whose bodies are a literal
    `return true;`/`return false;`) — the condition-chain grammar and
    walking logic is identical between the two idioms; only how the
    matched body is turned into a return value differs.

    Returns (body, blocked_by_missing_var):
      - (body, False) — a branch condition was fully evaluable and matched.
      - (None, False) — the script's grammar itself is unsupported (parse
        failure, no if-chain, nested if, etc.) — Tier 2 may still help here.
      - (None, True) — at least one condition couldn't be evaluated because
        a referenced variable is not filled yet, AND the chain never reached
        a short-circuit determination from the clauses that WERE known (see
        below). This is NOT a grammar problem — a Tier-2 LLM call has no more
        information than Tier 1 in this case (it cannot know a value that
        doesn't exist yet either), so callers should skip the LLM and treat
        this as "unknown for now" rather than spending a wasted round-trip.

    Short-circuits OR/AND chains: an OR chain that already hit `True` from
    an earlier known clause is `True` regardless of any later clause's
    variable being unfilled; symmetrically an AND chain that already hit
    `False` is `False` regardless of what comes after. Only when the result
    genuinely depends on an unfilled variable (a `False`-so-far OR chain, or
    a `True`-so-far AND chain, with a missing clause still in play) is the
    outcome truly unknown. Confirmed live this matters: a real hiding rule's
    condition is `region=="NA" OR country=="KY" OR customerType=="FEDERAL"`
    — for a US quote region is known ("NA", true) but customerType is
    typically never filled at all; without short-circuiting, this condition
    would forever report "unknown" instead of the true, already-determined
    "NA matched, don't hide" outcome.
    """
    branches = _parse_branches(script)
    if not branches:
        return None, False
    for cond, body in branches:
        if cond is None:
            return body, False
        # The whole chain is uniformly AND or OR (_parse_condition's own
        # contract) — only the first tuple's joiner is "" (a placeholder,
        # not "no chain"), so read the chain's real kind from any other
        # entry rather than per-tuple, or short-circuiting on clause 1
        # alone would never trigger.
        chain_joiner = next((j for j, *_ in cond if j), "")
        result: bool | None = None
        saw_missing = False
        short_circuited = False
        for joiner, var, op, expected in cond:
            actual = variables.get(var)
            if actual is None:
                saw_missing = True
                continue
            hit = actual.strip().lower() == expected.strip().lower()
            if op in ("<>", "!="):
                hit = not hit
            if result is None:
                result = hit
            elif joiner == "AND":
                result = result and hit
            else:
                result = result or hit
            if (chain_joiner == "AND" and result is False) or (chain_joiner == "OR" and result is True):
                short_circuited = True
                break
        if result is None or (saw_missing and not short_circuited):
            return None, True  # genuinely unresolvable with what's known so far
        if result:
            return body, False
    return None, False


def evaluate_declarative_conditions(
    conditions: list[tuple[int, str]], variables_by_id: dict[int, str],
) -> tuple[bool | None, bool]:
    """Evaluate a rule's FULL set of bm_config_rule_input rows (not just the
    last one — see HidingRule.conditions / ConstraintRule.conditions /
    RecommendationRule.conditions docstrings for why this replaces the old
    single condition_attr_id/condition_value pair for multi-input rules).

    Grouping rule: the SAME attribute_id repeated across rows means OR (any
    of that attribute's listed values matches); DIFFERENT attribute_ids are
    ANDed together. Confirmed live this matches real data: a rule like
    "Allow Multi-Code Plug Programming only when Enhancement Level is
    selected" repeats one attribute 3x with different ENHANCEMENT LEVEL
    values (an OR-list) alongside 2 other distinct attributes (ANDed in) —
    a real boolean expression, not a simple range.

    No operator1/operator2 distinction is made here (confirmed live: 0 of
    1,694 real rule_input rows in this catalog populate operator2/value2 at
    all, and operator1 is never consulted by the declarative evaluator this
    replaces either — matching prior behavior exactly, just extended to ALL
    inputs instead of only the last).

    Returns (result, blocked_by_missing_var):
      - (True, False)  — every attribute-group matched.
      - (False, False) — at least one attribute-group is known and did NOT
        match — short-circuits, same AND semantics as a script AND-chain
        already hitting False (see bml._first_matching_branch).
      - (None, True)   — one or more groups are still unresolved (attribute
        not filled yet) AND none of the known groups already disproved the
        condition — genuinely "not enough information yet," not a grammar
        problem, so callers should treat this the same as
        _first_matching_branch's own (None, True) case (no Tier-2 call,
        no premature fire).
      - (None, False)  — no conditions at all (empty list); callers should
        treat this the same as "no condition" (unresolved/unsupported).
    """
    if not conditions:
        return None, False
    by_attr: dict[int, list[str]] = {}
    order: list[int] = []
    for attr_id, value in conditions:
        if attr_id not in by_attr:
            order.append(attr_id)
        by_attr.setdefault(attr_id, []).append(value)

    saw_missing = False
    for attr_id in order:
        actual = variables_by_id.get(attr_id)
        if actual is None:
            saw_missing = True
            continue
        expected_values = by_attr[attr_id]
        # Each row's own value can itself be a "~"-delimited OR-list (same
        # encoding as ConstraintRule.allowed_values, e.g. a single input row
        # storing "PREMIER~ADVANCED SOFTWARE ONLY~ESSENTIAL SOFTWARE ONLY")
        # rather than always one literal value per row — a bare equality
        # check against the whole string can never match any one real value
        # in that case (confirmed live: this is exactly why "Hide Include
        # Accidental Damage for certain Service Type" never fired — see
        # docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md §3). Splitting each
        # row's value here is a strict superset of the old behavior — a
        # row with no "~" splits into a 1-element list, identical to before.
        expanded = {
            part.strip().lower()
            for v in expected_values
            for part in v.split("~")
            if part.strip()
        }
        hit = actual.strip().lower() in expanded
        if not hit:
            return False, False
    if saw_missing:
        return None, True
    return True, False


# Idiom B — "constant return", no CPQ attribute ever checked: no `if`
# anywhere, and the returned value is built entirely from quoted string
# literals and/or local helper variables that were themselves assigned a
# pure literal earlier in the same script (never a reference to a real
# config attribute). Confirmed live against real script-backed
# recommendations: "Set HelpTtext info" and "Populate Solution Set Array"
# both build an HTML-wrapped literal via local-variable + string
# concatenation (`Helptext = "..."; retVal = "<model...>"+"\""+...+Helptext+
# "</b></model>"; return retVal;`) — no branch, no attribute reference, so
# the result is the SAME every time regardless of catalog state.
_LOCAL_LITERAL_ASSIGN_RE = re.compile(
    r'(\w+)\s*=\s*"((?:[^"\\]|\\.)*)"\s*;',
)
_FINAL_RETURN_VAR_RE = re.compile(r'\breturn\s+(\w+)\s*;')
_ASSIGN_TO_RE = re.compile(r'(?<![=!<>])=(?!=)')


def evaluate_constant_return(script: str) -> str | None:
    """Tier 1.5: resolve a script to a constant string when it provably
    never branches AND never references a real CPQ attribute — see the
    idiom comment above. Returns None (not yet evaluated) rather than
    guessing whenever anything in the script isn't provably a literal.

    Deliberately conservative in three ways, each erring toward "unknown"
    rather than a wrong constant:
      - ANY `if (` anywhere bails immediately, even if unreachable.
      - The final `return <var>;` must name a variable whose LAST
        assignment is fully resolvable to quoted-literal concatenation —
        any unresolved identifier in that concatenation (i.e. anything
        that isn't a prior pure-literal local var) bails.
      - Multiple assignments to the same variable are walked in source
        order so the LAST one wins, matching normal execution order.
    """
    if re.search(r'\bif\s*\(', script, re.IGNORECASE):
        return None
    m = _FINAL_RETURN_VAR_RE.search(script)
    if not m:
        return None
    target_var = m.group(1)

    # Collect every "name = <rhs>;" statement in source order (rhs may be a
    # single quoted literal, or a +-concatenation of literals/known vars).
    # Split on `;` OUTSIDE quotes only — a naive re.split(';', ...) breaks on
    # scripts like the real "Set HelpTtext info" whose literal text itself
    # contains a semicolon (`"color:#FF0000; font-size:8pt;"`).
    literals: dict[str, str] = {}
    for stmt in _split_statements(script[:m.start()]):
        stmt = stmt.strip()
        if not stmt or not _ASSIGN_TO_RE.search(stmt):
            continue
        name, _, rhs = stmt.partition("=")
        name = name.strip()
        if not re.fullmatch(r'\w+', name):
            continue
        resolved = _resolve_literal_expr(rhs.strip(), literals)
        if resolved is not None:
            literals[name] = resolved
        else:
            literals.pop(name, None)  # now-unknown; a stale value would be wrong

    if target_var not in literals:
        return None
    return literals[target_var]


def _split_statements(text: str) -> list[str]:
    """Split BML source on `;` that are NOT inside a quoted string literal.

    A plain `text.split(';')` corrupts any statement whose literal text
    itself contains a semicolon — confirmed live: the real "Set HelpTtext
    info" script's own literal is `"color:#FF0000; font-size:8pt;"`, which
    a naive split fractures into three bogus statements.
    """
    stmts: list[str] = []
    buf: list[str] = []
    in_quotes = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"' and (i == 0 or text[i - 1] != "\\"):
            in_quotes = not in_quotes
            buf.append(ch)
        elif ch == ";" and not in_quotes:
            stmts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        stmts.append("".join(buf))
    return stmts


def _split_on_plus_outside_quotes(expr: str) -> list[str]:
    """Split on `+` that is NOT inside a quoted string literal — a literal
    like `"a+b"` must survive as one token, not split into `"a` / `b"`."""
    tokens: list[str] = []
    buf: list[str] = []
    in_quotes = False
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch == '"' and (i == 0 or expr[i - 1] != "\\"):
            in_quotes = not in_quotes
            buf.append(ch)
        elif ch == "+" and not in_quotes:
            tokens.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        tokens.append("".join(buf))
    return tokens


def _resolve_literal_expr(expr: str, literals: dict[str, str]) -> str | None:
    """Resolve a `+`-concatenation of quoted literals and/or known
    pure-literal identifiers to a single string, or None if any token isn't
    provably a literal (e.g. it references a real CPQ config attribute)."""
    parts: list[str] = []
    for token in _split_on_plus_outside_quotes(expr):
        token = token.strip()
        if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
            parts.append(token[1:-1].replace('\\"', '"'))
        elif re.fullmatch(r'\w+', token) and token in literals:
            parts.append(literals[token])
        else:
            return None
    return "".join(parts)


def evaluate_tier1(
    script: str, variables: dict[str, str],
) -> tuple[list[str] | None, bool]:
    """Deterministically evaluate a Tier-1 constraint/recommendation BML
    script (branch bodies are `returnVal = "A"|"B"` allowed-value lists).

    Returns (allowed_values, blocked_by_missing_var) — see
    _first_matching_branch for the exact semantics of each case.
    """
    body, blocked = _first_matching_branch(script, variables)
    if blocked:
        return None, True
    if body is None:
        return None, False
    return _branch_values(body), False


def evaluate_hide_tier1(
    script: str, variables: dict[str, str],
) -> tuple[bool | None, bool]:
    """Deterministically evaluate a Tier-1 hiding-rule BML script (branch
    bodies are literal `return true;`/`return false;` booleans).

    Returns (hide, blocked_by_missing_var) — see _first_matching_branch for
    the exact semantics of each case; True means the target attr should be
    hidden, False means it should stay visible.
    """
    body, blocked = _first_matching_branch(script, variables)
    if blocked:
        return None, True
    if body is None:
        return None, False
    return _branch_bool(body), False



# Process-wide cache, SHARED across every BmlEvaluator instance — i.e.
# across every CPQ turn and every concurrent request, not just within one.
# build_bml_evaluator() previously created a fresh, empty per-instance cache
# on every single turn, so the same script + same variable state paid the
# Tier-2 LLM cost again on every turn (and again for every other session
# hitting the same catalog). Keyed by (workspace_id, catalog_prefix, ...)
# so a BM-native function id that collides across two catalogs/workspaces
# sharing this process (confirmed happening earlier this session) can never
# share a cached — and possibly wrong — answer.
_SHARED_SCRIPT_CACHE: dict[tuple, list[str] | None] = {}
_MAX_SHARED_CACHE_ENTRIES = 20_000


def clear_shared_bml_cache() -> None:
    """Reset the process-wide script cache. Tests should call this between
    runs that mock different LLM responses for the same script/state, since
    the cache is otherwise shared across the whole test process."""
    _SHARED_SCRIPT_CACHE.clear()


class BmlEvaluator:
    """Two-tier BML evaluation with a process-wide (workspace, script, state) cache."""

    def __init__(
        self, scripts: dict[int, str], use_llm: bool = True,
        workspace_id: int = 0, catalog_prefix: str = "",
    ) -> None:
        """scripts — {bm_function_id: script_text} from the RDB.

        workspace_id/catalog_prefix scope the shared cache (see
        _SHARED_SCRIPT_CACHE) so results never cross-contaminate between
        catalogs or workspaces that happen to reuse the same BM-native
        function id.
        """
        self._scripts = scripts
        self._use_llm = use_llm
        self._workspace_id = workspace_id
        self._catalog_prefix = catalog_prefix
        self.stats = {"tier1": 0, "tier2": 0, "unknown": 0, "missing": 0, "cached": 0}

    def script_for(self, function_id: int) -> str | None:
        return self._scripts.get(function_id)

    def allowed_values(
        self, function_id: int, variables: dict[str, str],
    ) -> list[str] | None:
        """Allowed-value list for a rule action's BML function, or None."""
        script = self._scripts.get(function_id)
        if not script:
            self.stats["missing"] += 1
            return None
        return self.allowed_values_for_script(script, variables, cache_id=function_id)

    def allowed_values_for_script(
        self, script: str, variables: dict[str, str],
        cache_id: int | None = None,
    ) -> list[str] | None:
        """Allowed-value list for a raw BML script body, or None if unknown."""
        # referenced_variables() re-scans the whole script text with a regex —
        # compute it ONCE per call, not once per (variable, value) pair. With
        # ~170 filled variables and hundreds of script-backed constraint
        # rules active, doing this inside the generator below (as written
        # previously) re-parsed the same script ~170x per call — 71,490
        # redundant regex scans and ~155s of wasted CPU in one real turn.
        script_vars = referenced_variables(script)
        relevant = frozenset(
            (k, v) for k, v in variables.items()
            if k in script_vars
        )
        key = ("values", self._workspace_id, self._catalog_prefix,
               cache_id if cache_id is not None else hash(script), relevant)
        if key in _SHARED_SCRIPT_CACHE:
            self.stats["cached"] += 1
            return _SHARED_SCRIPT_CACHE[key]
        result, blocked_by_missing_var = evaluate_tier1(script, variables)
        if result is not None:
            self.stats["tier1"] += 1
        elif blocked_by_missing_var:
            # A referenced variable isn't filled yet — Tier 2 has no more
            # information than we do (it cannot know a value that doesn't
            # exist), so asking it would be a pure-waste round-trip. This
            # cache entry naturally becomes a miss again once the variable
            # gets filled, since `relevant` (and so `key`) changes.
            self.stats["unknown"] += 1
            result = None
        elif self._use_llm:
            result = self._evaluate_llm(script, dict(relevant))
            if result is not None:
                self.stats["tier2"] += 1
            else:
                self.stats["unknown"] += 1
        else:
            self.stats["unknown"] += 1
        if len(_SHARED_SCRIPT_CACHE) >= _MAX_SHARED_CACHE_ENTRIES:
            _SHARED_SCRIPT_CACHE.clear()
        _SHARED_SCRIPT_CACHE[key] = result
        return result

    def _evaluate_llm(
        self, script: str, variables: dict[str, str],
    ) -> list[str] | None:
        """Tier 2: ask the reason model to evaluate the script."""
        try:
            from aryx import llm_runtime
            sys_p = ("You evaluate BigMachines BML rule scripts. Given the "
                     "script and the current variable values, determine which "
                     "values the script allows (its returnVal, split on '|').")
            user_p = (f"Variables:\n{json.dumps(variables, indent=1)}\n\n"
                      f"Script:\n{script[:4000]}\n\n"
                      'Reply ONLY as JSON: {"allowed_values": ["..."]} or '
                      '{"unknown": true} if it cannot be determined.')
            # Tier-2 script interpretation genuinely needs reasoning (parse a
            # real BML script, hold its logic against current variable state,
            # commit to true/false/allowed-values) — moved from "menial" to
            # "answer" (ARYX_LLM_REASON_MODEL) since this is not the
            # lightweight term-extraction task "menial" is meant for.
            txt = llm_runtime.chat("answer", sys_p, user_p)[0]
            s, e = txt.find("{"), txt.rfind("}")
            if s == -1 or e <= s:
                return None
            d = json.loads(txt[s:e + 1])
            vals = d.get("allowed_values")
            if isinstance(vals, list):
                return [str(v) for v in vals if str(v).strip()]
        except Exception:  # noqa: BLE001 — LLM unavailable → unknown, not fatal
            logger.debug("bml: tier-2 LLM evaluation failed", exc_info=True)
        return None

    def should_hide(
        self, function_id: int, variables: dict[str, str],
    ) -> bool | None:
        """Hide/show decision for a hiding rule's BML function, or None if
        unknown (caller must treat None as "don't hide" — see
        CpqEngine.apply_hiding_rules)."""
        script = self._scripts.get(function_id)
        if not script:
            self.stats["missing"] += 1
            return None
        return self.hide_for_script(script, variables, cache_id=function_id)

    def hide_for_script(
        self, script: str, variables: dict[str, str],
        cache_id: int | None = None,
    ) -> bool | None:
        """Hide/show decision for a raw hiding-rule BML script body, or None
        if unknown. Mirrors allowed_values_for_script's tiering/caching, but
        for the hide-rule idiom (see evaluate_hide_tier1) rather than the
        constraint/recommendation allowed-values idiom."""
        script_vars = referenced_variables(script)
        relevant = frozenset(
            (k, v) for k, v in variables.items()
            if k in script_vars
        )
        key = ("hide", self._workspace_id, self._catalog_prefix,
               cache_id if cache_id is not None else hash(script), relevant)
        if key in _SHARED_SCRIPT_CACHE:
            self.stats["cached"] += 1
            return _SHARED_SCRIPT_CACHE[key]
        result, blocked_by_missing_var = evaluate_hide_tier1(script, variables)
        if result is not None:
            self.stats["tier1"] += 1
        elif blocked_by_missing_var:
            self.stats["unknown"] += 1
            result = None
        elif self._use_llm:
            result = self._evaluate_llm_hide(script, dict(relevant))
            if result is not None:
                self.stats["tier2"] += 1
            else:
                self.stats["unknown"] += 1
        else:
            self.stats["unknown"] += 1
        if len(_SHARED_SCRIPT_CACHE) >= _MAX_SHARED_CACHE_ENTRIES:
            _SHARED_SCRIPT_CACHE.clear()
        _SHARED_SCRIPT_CACHE[key] = result
        return result

    def _evaluate_llm_hide(
        self, script: str, variables: dict[str, str],
    ) -> bool | None:
        """Tier 2: ask the reason model for a hiding rule's hide/show outcome."""
        try:
            from aryx import llm_runtime
            sys_p = ("You evaluate BigMachines BML hiding-rule scripts. Given "
                     "the script and the current variable values, determine "
                     "whether the script's logic hides the target attribute "
                     "(true) or keeps it visible (false).")
            user_p = (f"Variables:\n{json.dumps(variables, indent=1)}\n\n"
                      f"Script:\n{script[:4000]}\n\n"
                      'Reply ONLY as JSON: {"hide": true} or {"hide": false} '
                      'or {"unknown": true} if it cannot be determined.')
            # Tier-2 script interpretation genuinely needs reasoning (parse a
            # real BML script, hold its logic against current variable state,
            # commit to true/false/allowed-values) — moved from "menial" to
            # "answer" (ARYX_LLM_REASON_MODEL) since this is not the
            # lightweight term-extraction task "menial" is meant for.
            txt = llm_runtime.chat("answer", sys_p, user_p)[0]
            s, e = txt.find("{"), txt.rfind("}")
            if s == -1 or e <= s:
                return None
            d = json.loads(txt[s:e + 1])
            if d.get("unknown"):
                return None
            hide = d.get("hide")
            if isinstance(hide, bool):
                return hide
        except Exception:  # noqa: BLE001 — LLM unavailable → unknown, not fatal
            logger.debug("bml: tier-2 LLM hide-evaluation failed", exc_info=True)
        return None

    def condition_holds(
        self, script: str, variables: dict[str, str],
        cache_id: int | None = None,
    ) -> bool | None:
        """True/False/unknown for a rule's own boolean condition script.

        Distinct from hide_for_script even though Tier 1 reuses the same
        structural if/else-chain-returning-true/false parser (evaluate_hide_tier1
        is generic — nothing about it is specific to hide/show semantics,
        only its NAME is). Kept as a separate method (not an alias) because
        Tier 2 needs its own LLM wording: hide_for_script's prompt explicitly
        asks the model to reason about "hides the target attribute," which
        is the wrong question for a rule condition that gates a declarative
        recommend/restrict action rather than a hide decision. Uses a
        distinct cache-key prefix ("cond") so a script's hide-decision and
        condition-decision can never collide even if reused across both
        (BM-native ids are only unique within one export, not globally)."""
        script_vars = referenced_variables(script)
        relevant = frozenset(
            (k, v) for k, v in variables.items()
            if k in script_vars
        )
        key = ("cond", self._workspace_id, self._catalog_prefix,
               cache_id if cache_id is not None else hash(script), relevant)
        if key in _SHARED_SCRIPT_CACHE:
            self.stats["cached"] += 1
            return _SHARED_SCRIPT_CACHE[key]
        result, blocked_by_missing_var = evaluate_hide_tier1(script, variables)
        if result is not None:
            self.stats["tier1"] += 1
        elif blocked_by_missing_var:
            self.stats["unknown"] += 1
            result = None
        elif self._use_llm:
            result = self._evaluate_llm_condition(script, dict(relevant))
            if result is not None:
                self.stats["tier2"] += 1
            else:
                self.stats["unknown"] += 1
        else:
            self.stats["unknown"] += 1
        if len(_SHARED_SCRIPT_CACHE) >= _MAX_SHARED_CACHE_ENTRIES:
            _SHARED_SCRIPT_CACHE.clear()
        _SHARED_SCRIPT_CACHE[key] = result
        return result

    def _evaluate_llm_condition(
        self, script: str, variables: dict[str, str],
    ) -> bool | None:
        """Tier 2: ask the reason model whether a rule's condition fires."""
        try:
            from aryx import llm_runtime
            sys_p = ("You evaluate BigMachines BML rule-condition scripts. Given "
                     "the script and the current variable values, determine "
                     "whether the script's condition evaluates to true (the "
                     "rule fires) or false (it does not).")
            user_p = (f"Variables:\n{json.dumps(variables, indent=1)}\n\n"
                      f"Script:\n{script[:4000]}\n\n"
                      'Reply ONLY as JSON: {"condition_true": true} or '
                      '{"condition_true": false} or {"unknown": true} if it '
                      'cannot be determined.')
            # Tier-2 script interpretation genuinely needs reasoning (parse a
            # real BML script, hold its logic against current variable state,
            # commit to true/false/allowed-values) — moved from "menial" to
            # "answer" (ARYX_LLM_REASON_MODEL) since this is not the
            # lightweight term-extraction task "menial" is meant for.
            txt = llm_runtime.chat("answer", sys_p, user_p)[0]
            s, e = txt.find("{"), txt.rfind("}")
            if s == -1 or e <= s:
                return None
            d = json.loads(txt[s:e + 1])
            if d.get("unknown"):
                return None
            val = d.get("condition_true")
            if isinstance(val, bool):
                return val
        except Exception:  # noqa: BLE001 — LLM unavailable → unknown, not fatal
            logger.debug("bml: tier-2 LLM condition-evaluation failed", exc_info=True)
        return None
