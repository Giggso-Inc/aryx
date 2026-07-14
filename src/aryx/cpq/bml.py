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

logger = logging.getLogger(__name__)

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


def _parse_condition(cond: str) -> list[tuple[str, str, str, str]] | None:
    """Parse a condition into [(joiner, var, op, value)]; None if unsupported.

    Supports single comparisons and chains joined by a uniform AND or OR.
    The first tuple's joiner is ''.
    """
    cond = cond.strip()
    for joiner, sep in (("AND", re.compile(r'\bAND\b|&&', re.IGNORECASE)),
                        ("OR", re.compile(r'\bOR\b|\|\|', re.IGNORECASE))):
        parts = sep.split(cond)
        if len(parts) > 1:
            out = []
            for i, part in enumerate(parts):
                m = _CMP_RE.match(part)
                if not m:
                    return None
                out.append(("" if i == 0 else joiner, m.group(1), m.group(2), m.group(3)))
            return out
    m = _CMP_RE.match(cond)
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


def referenced_variables(script: str) -> set[str]:
    """Variable names compared in the script (Tier-1 scan, best effort)."""
    return {m.group(1) for m in re.finditer(r'(\w+)\s*(?:==|<>|!=)\s*"', script)}


def evaluate_tier1(
    script: str, variables: dict[str, str],
) -> tuple[list[str] | None, bool]:
    """Deterministically evaluate a Tier-1 BML script.

    Returns (allowed_values, blocked_by_missing_var):
      - (values, False) — a branch condition was fully evaluable and matched.
      - (None, False) — the script's grammar itself is unsupported (parse
        failure, no if-chain, nested if, etc.) — Tier 2 may still help here.
      - (None, True) — at least one condition couldn't be evaluated because
        a referenced variable is not filled yet. This is NOT a grammar
        problem — a Tier-2 LLM call has no more information than Tier 1 in
        this case (it cannot know a value that doesn't exist yet either),
        so callers should skip the LLM and treat this as "unknown for now"
        rather than spending a wasted round-trip.
    """
    branches = _parse_branches(script)
    if not branches:
        return None, False
    for cond, body in branches:
        if cond is None:
            return _branch_values(body), False
        result: bool | None = None
        for joiner, var, op, expected in cond:
            actual = variables.get(var)
            if actual is None:
                return None, True  # variable not filled yet → outcome unknown
            hit = actual.strip().lower() == expected.strip().lower()
            if op in ("<>", "!="):
                hit = not hit
            if result is None:
                result = hit
            elif joiner == "AND":
                result = result and hit
            else:
                result = result or hit
        if result:
            return _branch_values(body), False
    return None, False



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
        key = (self._workspace_id, self._catalog_prefix,
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
