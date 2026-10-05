"""Tier-1 deterministic BML evaluation entry points: branch-chain walking,
constant-return resolution, and the process-wide script cache.

Split out of `cpq/bml.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See `bml_text.py`'s docstring for the zero-patch-risk basis.
"""
from __future__ import annotations

import logging
import re

from aryx.cpq.bml.bml_branches import _branch_bool, _branch_values, _parse_branches
from aryx.cpq.bml.bml_conditions import (
    _ARRAY_IN_OP,
    _ARRAY_NOT_IN_OP,
    _array_membership_hit,
    _eval_boolean_expr,
    _BoolExpr,
)
from aryx.cpq.bml.bml_find import FIND_OP, find_enabled, find_haystack, find_hit, starts_with_if
from aryx.cpq.bml.bml_hide_idioms import evaluate_hide_master_list, evaluate_hide_master_list_unguarded
from aryx.cpq.bml.bml_text import _split_on_plus_outside_quotes, _split_statements

logger = logging.getLogger(__name__)


def _descend(body: str, variables: dict[str, str]) -> tuple[str | None, bool]:
    """Matched branch body; when it is itself an if-chain (plan F14, flag
    `cpq_find_function_enabled`) resolve the nested chain the same way.
    Flag off or a plain body: `(body, False)` -- unchanged behaviour."""
    if find_enabled() and starts_with_if(body):
        return _first_matching_branch(body, variables)
    return body, False


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
            return _descend(body, variables)
        if isinstance(cond, _BoolExpr):
            # docs/CPQ_TIER1_MIXED_AND_OR_CONDITION_PARSER_PLAN_2026_08_10.md
            # -- this branch's condition mixed AND and OR and needed the
            # separate recursive parser/evaluator; every condition
            # _parse_condition itself resolves never takes this path.
            result, blocked = _eval_boolean_expr(cond, variables)
            if result is None:
                return None, blocked
            if result:
                return _descend(body, variables)
            continue
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
            actual = find_haystack(variables, var, expected) if op == FIND_OP else variables.get(var)
            if actual is None:
                saw_missing = True
                continue
            if op == FIND_OP:
                hit = find_hit(actual, expected)
            elif op in (_ARRAY_IN_OP, _ARRAY_NOT_IN_OP):
                hit = _array_membership_hit(actual, op, expected)
            else:
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
            return _descend(body, variables)
    return None, False

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

    Tries Idiom C (evaluate_hide_master_list), then Idiom D
    (evaluate_hide_master_list_unguarded) — two different grammar shapes
    _first_matching_branch's if/else-if/else chain parser was never meant
    to recognize — and falls through to the chain parser only when neither
    idiom matches ((None, False) from both).
    """
    result, blocked = evaluate_hide_master_list(script, variables)
    if blocked or result is not None:
        return result, blocked
    result, blocked = evaluate_hide_master_list_unguarded(script, variables)
    if blocked or result is not None:
        return result, blocked
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
