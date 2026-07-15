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

Tier 2 — LLM fallback: scripts Tier 1 cannot parse are handed to the menial
model with the current variable state; the reply is a JSON allowed-values
list. Results are cached per (script, relevant-variable-state).

Both tiers return ``None`` when the outcome is unknown (unparseable script,
referenced variable not yet filled, LLM unavailable) — the caller treats
None as "no constraint derived", never as "everything allowed".
"""
from __future__ import annotations

import json
import logging
import re

from aryx.cpq.logging_context import install_run_id_logging

logger = logging.getLogger(__name__)
install_run_id_logging(__name__)

# variable == "value" / variable <> "value" comparisons inside a condition
_CMP_RE = re.compile(r'^\s*(\w+)\s*(==|<>|!=)\s*"([^"]*)"\s*$')

# returnVal = "A"|"B"|... assignment inside a branch body
_ASSIGN_RE = re.compile(r'return[Vv]al\s*=\s*((?:"[^"]*"\s*(?:\|\s*)?)+);?')
_STR_RE = re.compile(r'"([^"]*)"')

# if (...) { ... } chain scanner
_IF_RE = re.compile(r'\bif\s*\(', re.IGNORECASE)

# Constructs that put a script beyond Tier 1 (function calls, nesting hints).
_TIER1_BLOCKERS = re.compile(
    r'\b(for|while|foreach|util\.|usersessionget|jsonarray|dict\(|urldata)\b',
    re.IGNORECASE,
)


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
                out.append(("" if i == 0 else joiner, m.group(1), m.group(2), m.group(3)))
            return out
    m = _CMP_RE.match(_strip_wrapping_parens(cond))
    if m:
        return [("", m.group(1), m.group(2), m.group(3))]
    return None


def _parse_branches(script: str) -> list[tuple[list | None, str]] | None:
    """Parse an if / else-if / else chain into [(condition, body)].

    condition is the _parse_condition output, or None for the else branch.
    Returns None when the script doesn't fit the Tier-1 idiom.
    """
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


def _branch_values(body: str) -> list[str] | None:
    """Extract the pipe-delimited allowed-value list from a branch body."""
    m = _ASSIGN_RE.search(body)
    if not m:
        return None
    values = [v.strip() for v in _STR_RE.findall(m.group(1))]
    return [v for v in values if v and v != "|"]


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
        hit = any(actual.strip().lower() == v.strip().lower() for v in expected_values)
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
        """Tier 2: ask the menial model to evaluate the script."""
        try:
            from aryx import llm_runtime
            sys_p = ("You evaluate BigMachines BML rule scripts. Given the "
                     "script and the current variable values, determine which "
                     "values the script allows (its returnVal, split on '|').")
            user_p = (f"Variables:\n{json.dumps(variables, indent=1)}\n\n"
                      f"Script:\n{script[:4000]}\n\n"
                      'Reply ONLY as JSON: {"allowed_values": ["..."]} or '
                      '{"unknown": true} if it cannot be determined.')
            txt = llm_runtime.chat("menial", sys_p, user_p)[0]
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
        """Tier 2: ask the menial model for a hiding rule's hide/show outcome."""
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
            txt = llm_runtime.chat("menial", sys_p, user_p)[0]
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
