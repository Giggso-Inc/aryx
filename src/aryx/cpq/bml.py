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


def evaluate_tier1(script: str, variables: dict[str, str]) -> list[str] | None:
    """Deterministically evaluate a Tier-1 BML script.

    Returns the allowed-value list from the first branch whose condition
    holds, or None when the script is out of grammar or references a
    variable that is not filled yet.
    """
    branches = _parse_branches(script)
    if not branches:
        return None
    for cond, body in branches:
        if cond is None:
            return _branch_values(body)
        result: bool | None = None
        for joiner, var, op, expected in cond:
            actual = variables.get(var)
            if actual is None:
                return None  # variable not filled yet → outcome unknown
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
            return _branch_values(body)
    return None


class BmlEvaluator:
    """Two-tier BML evaluation with per-(script, state) caching."""

    def __init__(self, scripts: dict[int, str], use_llm: bool = True) -> None:
        """scripts — {bm_function_id: script_text} from the RDB."""
        self._scripts = scripts
        self._use_llm = use_llm
        self._cache: dict[tuple[int, frozenset], list[str] | None] = {}
        self.stats = {"tier1": 0, "tier2": 0, "unknown": 0, "missing": 0}

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
        relevant = frozenset(
            (k, v) for k, v in variables.items()
            if k in referenced_variables(script)
        )
        key = (cache_id if cache_id is not None else hash(script), relevant)
        if key in self._cache:
            return self._cache[key]
        result = evaluate_tier1(script, variables)
        if result is not None:
            self.stats["tier1"] += 1
        elif self._use_llm:
            result = self._evaluate_llm(script, dict(relevant))
            if result is not None:
                self.stats["tier2"] += 1
            else:
                self.stats["unknown"] += 1
        else:
            self.stats["unknown"] += 1
        self._cache[key] = result
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
