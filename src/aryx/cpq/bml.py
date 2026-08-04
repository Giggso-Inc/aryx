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
import hashlib
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

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

# docs/config_consistency_issues_2026-07-30.md issue 2 follow-up —
# live-confirmed real APX Next scripts build a |^|-delimited allowed-list
# via STRING CONCATENATION instead of one packed literal, e.g.
# `retVal = "CORE BUNDLE" + "|^|" + "SECURITY BUNDLE" + "|^|" + ...;` —
# a DIFFERENT authoring style than `_split_pipe_caret_values`'s existing
# single-literal `"A|^|B|^|C"` case. `_ASSIGN_RE`/`_RETURN_STR_RE` only
# match the FIRST quoted fragment here, and the concatenation guard below
# (existing, correctly built for the SVX HTML-building case where a real
# variable like `link` is mixed into the chain) then bails as
# unparseable — correct for a GENUINELY dynamic chain, but this shape is
# not dynamic at all: every single term is a quoted literal, nothing else.
# Fully statically resolvable — just authored with `+` instead of one
# big string.
_FULL_LITERAL_CONCAT_RE = re.compile(r'^(?:"[^"]*"\s*\+\s*)*"[^"]*"\s*;?\s*$')
# A pure delimiter literal (`|^|`, `|`, etc.) — never a real catalog value,
# must be filtered out of the extracted literal chain.
_PURE_DELIMITER_RE = re.compile(r'^\|[^|"]*\|$|^\|$')


def _literal_concat_values(rhs: str) -> list[str] | None:
    """If `rhs` (everything from right after the `=`/`return` through the
    terminating `;`) is ENTIRELY a chain of quoted-string literals joined
    by `+` — no variables, no function calls, nothing else — return the
    non-delimiter literals in order. Returns None when the chain contains
    anything else at all; a real variable/expression genuinely can't be
    resolved statically and this must never guess at one (same "never
    guess" discipline as everywhere else in this module).
    """
    rhs = rhs.strip()
    if not rhs or not _FULL_LITERAL_CONCAT_RE.match(rhs):
        return None
    literals = _STR_RE.findall(rhs)
    return [v for v in literals if v and not _PURE_DELIMITER_RE.match(v)]


# Full right-hand-side of a returnVal/return assignment, from right after
# the `=`/keyword through the terminating `;` — used only by the literal-
# concatenation fallback above, which needs the WHOLE chain, not just the
# first fragment `_ASSIGN_RE`/`_RETURN_STR_RE` themselves capture.
_FULL_ASSIGN_RHS_RE = re.compile(r're(?:t|turn)[Vv]al\s*=\s*(.+?);', re.DOTALL)
_FULL_RETURN_RHS_RE = re.compile(r'\breturn\s+(.+?);', re.DOTALL)

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


def _strip_block_comments(text: str) -> str:
    """Strip `/* ... */` block comments, but never inside a quoted string
    literal — same string-awareness as `_strip_line_comments`, which only
    handles `//` and leaves `/* */` untouched.

    Live-confirmed bug (2026-07-28): a real constraint script
    ("Restrict APX Next Product Selection based on HW Version selection")
    wraps a dead scratch block in `/* ... */` referencing `usersessionget`/
    `util.*` — both `_TIER1_BLOCKERS` triggers. Because this comment was
    never stripped, its dead reference alone rejected an otherwise
    trivially Tier-1-parseable if/else script, forcing every evaluation of
    it into the shared, per-turn-capped Tier-2 LLM path for no reason.
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
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            if j == -1:
                break
            i = j + 2
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


_BARE_RETURN_RE = re.compile(r'\A\s*return\s+.+?;\s*\Z', re.IGNORECASE | re.DOTALL)


def _parse_branches(script: str) -> list[tuple[list | None, str]] | None:
    """Parse an if / else-if / else chain into [(condition, body)].

    condition is the _parse_condition output, or None for the else branch.
    Returns None when the script doesn't fit the Tier-1 idiom.
    """
    script = _strip_block_comments(_strip_line_comments(script))
    branches: list[tuple[list | None, str]] = []
    m = _IF_RE.search(script)
    if not m:
        # No if/else at all — a common, genuinely trivial idiom: the WHOLE
        # script is just one unconditional `return <value>;` (confirmed
        # live: workspace 39004's "Set default to Baseline Release for
        # Baseline Release SW" — `return "BASELINE RELEASE";`, no
        # condition whatsoever). Before this, ANY script shaped this way
        # reported "grammar unsupported" and needed Tier 2 — but
        # settings.bml_use_llm is off by default (deliberately, to avoid
        # a live request stalling on a slow/rate-limited LLM call), so in
        # practice these scripts silently resolved to nothing at all,
        # letting a rule-governed attribute's OWN unrelated "first
        # eligible option by order" fallback (CpqEngine.auto_fill step 5)
        # claim it instead — e.g. baselineReleaseSW_astro's real answer
        # ("BASELINE RELEASE", the canonical spelling) was silently
        # replaced by "YES" (a legacy same-display-label sibling option,
        # just the first one by catalog order_number), even though the
        # rule that was SUPPOSED to set it never got the chance to fire.
        # A single unconditional return needs no branch/condition
        # machinery at all — treat it as one universal branch (cond=None,
        # always matches) and reuse the exact same _branch_values/
        # _branch_bool body-parsing _first_matching_branch already trusts
        # for every other branch body, so this idiom gets neither more
        # nor less scrutiny than a real if/else chain's own bodies.
        bare = script.strip()
        if bare and _BARE_RETURN_RE.match(bare) and not _TIER1_BLOCKERS.search(bare):
            return [(None, bare)]
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
        cond_text = text[paren_start + 1:cond_end]
        if _TIER1_BLOCKERS.search(cond_text):
            return None
        cond = _parse_condition(cond_text)
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
        if _TIER1_BLOCKERS.search(body):
            return None
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
            if _TIER1_BLOCKERS.search(body2):
                return None
            branches.append((None, body2))
            break
        # Amendment 19 follow-up (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md):
        # a single if{...} block with NO `else` keyword at all, followed by
        # exactly one bare `return true;`/`return false;` and nothing else,
        # is a common real idiom — an implicit else expressed as a
        # fallthrough rather than an explicit else block (confirmed live:
        # "Hide Video Streaming Devices for FedRamp" —
        # `if(x=="Y"){return true;} return false;`). Without this, a false
        # condition made the whole script report as unparseable instead of
        # correctly falling through to `false` — forcing an avoidable
        # Tier-2 call for a script Tier 1 can actually resolve completely.
        #
        # Deliberately restricted to a bare BOOLEAN literal, not any
        # `return <literal>;` — a bare `return "";` (empty string) is a
        # real, different, already-tested idiom (SVX's "Set defaults for
        # VX650": `if(cond){return "YES";} return "";`) where empty-string
        # means "no recommendation" and must stay `None`, not become an
        # inferred branch — see test_real_script_does_not_force_yes_when_
        # condition_false. Booleans have no such "empty means nothing"
        # ambiguity, so this is safe to infer; quoted-string returns are
        # not, and are intentionally left untouched.
        if len(branches) == 1 and not _IF_RE.search(rest):
            m_tail = re.match(r'return\s+(true|false)\s*;\s*$', rest, re.IGNORECASE)
            if m_tail:
                branches.append((None, rest))
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
            _full = _FULL_RETURN_RHS_RE.search(body)
            _literal_vals = (
                _literal_concat_values(_full.group(1)) if _full else None
            )
            if _literal_vals is not None:
                return _split_pipe_caret_values(_literal_vals)
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
        # docs/config_consistency_issues_2026-07-30.md issue 2 follow-up —
        # try the fully-literal concatenation fallback FIRST: real APX Next
        # scripts build a |^|-delimited allowed-list via `"A" + "|^|" +
        # "B" + ...` — every term a quoted literal, genuinely resolvable —
        # before falling back to the WARNING/unparseable path below, which
        # stays correct for an actually dynamic chain (a real variable
        # mixed in, e.g. the SVX HTML-building case this guard was
        # originally built for).
        _full = _FULL_ASSIGN_RHS_RE.search(body)
        _literal_vals = _literal_concat_values(_full.group(1)) if _full else None
        if _literal_vals is not None:
            return _split_pipe_caret_values(_literal_vals)
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
    return {
        m.group(1) for m in re.finditer(
            r'(\w+)\s*(?:==|<>|!=)\s*(?:"[^"]*"|true\b|false\b)', script, re.IGNORECASE)
    }


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


_NUMERIC_OPERATORS = frozenset({"1", "2", "5"})  # <, <=, >
_NOT_EQUAL_OPERATOR = "3"
# "7"/"8" — multi-select ("~"-joined current-selection set) membership,
# confirmed via docs/CPQ_DECLARATIVE_CONDITION_OPERATOR_PLAN_2026_08_05.md
# Phase 2: 104/110 real op7/op8 rows target an attribute classify_select_type
# already independently calls "multi" (checkbox); the remaining 6 are all
# _BM_USER_GROUPS, a BM system membership pseudo-attribute — same set-
# intersection semantic, just against the user's group membership set
# instead of a menu attribute's current selections. "7" = the current
# selection set intersects the rule's expected value(s) ("Do not allow
# Smartlocate to be deselected when Smartvideo or SmartEvidence selected"
# uses op7 as an OR across SMARTVIDEO/SMARTEVIDENCE). "8" = the current
# selection set does NOT intersect the expected value(s) ("...only when
# Enhancement Level is selected" uses op8 on both ENHANCEMENT LEVEL 1 and
# LEVEL 2 as the rule's own failure condition -- fires, i.e. blocks, when
# NEITHER is selected; "Hide Smartvideo help text if Smartvideo not
# selected" uses op8 directly on SMARTVIDEO).
_MULTI_SELECT_CONTAINS_OPERATOR = "7"
_MULTI_SELECT_NOT_CONTAINS_OPERATOR = "8"
_MULTI_SELECT_OPERATORS = frozenset(
    {_MULTI_SELECT_CONTAINS_OPERATOR, _MULTI_SELECT_NOT_CONTAINS_OPERATOR}
)


def _operator_hit(actual: str, expected_values: list[str], operator: str) -> bool | None:
    """Does `actual` satisfy `expected_values` under the given BM-native
    operator code? Returns None when a numeric operator can't parse either
    side — never guessed, same D2 discipline as every other unresolvable
    case in this module.

    expected_values may itself contain "~"-delimited OR-lists per value
    (same convention as ConstraintRule.allowed_values) — expanded into a
    flat set for "=", "<>", "7" and "8" (membership / non-membership
    against the whole set). Numeric operators (<, <=, >) compare against
    the single expected value directly — real catalog data never carries a
    "~"-list for a numeric bound (confirmed: docs/CPQ_DECLARATIVE_
    CONDITION_OPERATOR_PLAN_2026_08_05.md's audit found no such case).

    Mapping confirmed via docs/CPQ_DECLARATIVE_CONDITION_OPERATOR_PLAN_
    2026_08_05.md: "4"="=" (default/majority, 31/31 rule-name cross-check
    for "3"), "3"="<>", "1"="<", "2"="<=", "5"=">", "7"="intersects"/
    "8"="disjoint from" (Phase 2, 104/110 real rows target a
    select_type=="multi" attr, cross-checked against 4 independently
    -authored rule names — see the constants above for detail).

    For "7"/"8", `actual` is itself allowed to be a "~"-joined SET (a
    multi-select attr's current selections), not just a scalar — checked
    via set intersection with `expected_values` rather than the scalar
    membership check the other operators use. A plain scalar with no "~"
    still works correctly here: it just becomes a one-element set.
    """
    actual_norm = actual.strip().lower()
    if operator in _NUMERIC_OPERATORS:
        try:
            actual_num = float(actual)
            expected_num = float(expected_values[0]) if expected_values else None
        except (TypeError, ValueError):
            return None
        if expected_num is None:
            return None
        if operator == "1":
            return actual_num < expected_num
        if operator == "2":
            return actual_num <= expected_num
        return actual_num > expected_num  # "5"

    expanded = {
        part.strip().lower()
        for v in expected_values
        for part in v.split("~")
        if part.strip()
    }

    if operator in _MULTI_SELECT_OPERATORS:
        actual_set = {part.strip().lower() for part in actual.split("~") if part.strip()}
        intersects = bool(actual_set & expanded)
        return intersects if operator == _MULTI_SELECT_CONTAINS_OPERATOR else not intersects

    hit = actual_norm in expanded
    if operator == _NOT_EQUAL_OPERATOR:
        return not hit
    return hit  # "4"


def evaluate_declarative_conditions(
    conditions: list[tuple[int, str, str]], variables_by_id: dict[int, str],
) -> tuple[bool | None, bool]:
    """Evaluate a rule's FULL set of bm_config_rule_input rows (not just the
    last one — see HidingRule.conditions / ConstraintRule.conditions /
    RecommendationRule.conditions docstrings for why this replaces the old
    single condition_attr_id/condition_value pair for multi-input rules).

    Grouping rule: the SAME attribute_id repeated across rows means OR (any
    of that attribute's listed values matches, or none of them does for
    "<>" — see _operator_hit); DIFFERENT attribute_ids are ANDed together.
    Confirmed live this matches real data: a rule like "Allow Multi-Code
    Plug Programming only when Enhancement Level is selected" repeats one
    attribute 3x with different ENHANCEMENT LEVEL values (an OR-list)
    alongside 2 other distinct attributes (ANDed in) — a real boolean
    expression, not a simple range.

    operator1 IS now consulted, via _operator_hit — see that function's
    docstring and docs/CPQ_DECLARATIVE_CONDITION_OPERATOR_PLAN_2026_08_05.md
    for the confirmed mapping and why the prior "always =" behavior was
    wrong for 25.5% of real condition rows in one catalog. Every row for
    the same attr_id is assumed to share one operator (mixing "=" and "<>"
    within one OR-group was never observed in the confirmed audit); the
    first row's operator is used for the whole group.

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
    op_by_attr: dict[int, str] = {}
    order: list[int] = []
    for attr_id, value, operator in conditions:
        if attr_id not in by_attr:
            order.append(attr_id)
            op_by_attr[attr_id] = operator
        by_attr.setdefault(attr_id, []).append(value)

    saw_missing = False
    for attr_id in order:
        actual = variables_by_id.get(attr_id)
        if actual is None:
            saw_missing = True
            continue
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
        # _operator_hit handles the "~"-expansion itself.
        hit = _operator_hit(actual, by_attr[attr_id], op_by_attr[attr_id])
        if hit is None:
            saw_missing = True
            continue
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


# Idiom C — "hide unless present in a master delimited list": a shape
# distinct from the if/else-if/else chain _first_matching_branch parses —
# one guarded if-block, no branch-vs-branch comparison at all. Found live
# investigating Amendment 18's 121 hiding-rule targets that fell through to
# Tier 2 despite depending on nothing but two already-filled variables — the
# grammar, not missing data, was the blocker. Confirmed identical shape
# across dozens of real rules in the CommandCentral Aware catalog (e.g.
# "Hide Third Party Vendor Name if no values available", "Hide QTY Included
# array if not values are available", "Hide Connector Type Included array if
# not values are available", ...), differing only in which master/separator
# variable and which literal name they check for:
#
#   if(MASTER<>""){
#   ARR = SPLIT(MASTER,SEP);
#   IDX = findinarray(ARR,"LITERAL");
#      if (IDX ==-1){
#          return TRUE;
#      }
#      }
#   return FALSE;
#
# Semantics: hide the target UNLESS "LITERAL" appears in MASTER's own value
# once split on SEP's own value (an empty/missing MASTER never hides — the
# outer guard is false, so it falls straight to `return FALSE`).
# `re.fullmatch` (not `search`) against the whole comment-stripped script:
# anything beyond this exact shape bails to None rather than guessing.
_COMMENT_RE = re.compile(r'/\*.*?\*/', re.DOTALL)
_HIDE_MASTER_LIST_RE = re.compile(
    r'if\s*\(\s*(?P<master>\w+)\s*<>\s*""\s*\)\s*\{\s*'
    r'(?P<arr>\w+)\s*=\s*SPLIT\s*\(\s*(?P=master)\s*,\s*(?P<sep>\w+)\s*\)\s*;\s*'
    r'(?P<idx>\w+)\s*=\s*findinarray\s*\(\s*(?P=arr)\s*,\s*"(?P<literal>[^"]*)"\s*\)\s*;\s*'
    r'if\s*\(\s*(?P=idx)\s*==\s*-1\s*\)\s*\{\s*'
    r'return\s+true\s*;\s*'
    r'\}\s*'
    r'\}\s*'
    r'return\s+false\s*;\s*',
    re.IGNORECASE,
)


def evaluate_hide_master_list(
    script: str, variables: dict[str, str],
) -> tuple[bool | None, bool]:
    """Tier 1.5 (Idiom C): resolve the "hide unless in master list" idiom
    deterministically. Returns (hide, blocked_by_missing_var) — same
    contract as evaluate_hide_tier1/_first_matching_branch. (None, False)
    means the script isn't this idiom at all (try the next tier); (None,
    True) means it IS this idiom but MASTER or SEP isn't filled yet.
    """
    m = _HIDE_MASTER_LIST_RE.fullmatch(_COMMENT_RE.sub("", script).strip())
    if not m:
        return None, False
    master = variables.get(m.group("master"))
    sep = variables.get(m.group("sep"))
    if master is None or sep is None:
        return None, True
    if master == "":
        return False, False
    return m.group("literal") not in master.split(sep), False


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

    Tries Idiom C (evaluate_hide_master_list) first — a different grammar
    shape _first_matching_branch's if/else-if/else chain parser was never
    meant to recognize — and falls through to the chain parser only when
    Idiom C reports "not this shape" ((None, False)).
    """
    result, blocked = evaluate_hide_master_list(script, variables)
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


class BmlEvaluator:
    """Two-tier BML evaluation with a process-wide (workspace, script, state) cache."""

    def __init__(
        self, scripts: dict[int, str], use_llm: bool = True,
        workspace_id: int = 0, catalog_prefix: str = "",
        tier2_max_per_turn: int | None = None,
    ) -> None:
        """scripts — {bm_function_id: script_text} from the RDB.

        workspace_id/catalog_prefix scope the shared cache (see
        _SHARED_SCRIPT_CACHE) so results never cross-contaminate between
        catalogs or workspaces that happen to reuse the same BM-native
        function id.

        tier2_max_per_turn (Amendment 18): a hard ceiling on distinct
        Tier-2 attempts across this evaluator's WHOLE lifetime — one
        instance lives for exactly one CPQ turn (built fresh per turn by
        CpqEngine.build_bml_evaluator), so this naturally caps "per turn,
        across every pass of evaluate_rules_loop combined." None defaults
        to settings.bml_tier2_max_per_turn. A `threading.Lock` guards the
        check-and-increment since prefetch_tier2 dispatches concurrently
        from multiple threads.
        """
        self._scripts = scripts
        self._use_llm = use_llm
        self._workspace_id = workspace_id
        self._catalog_prefix = catalog_prefix
        if tier2_max_per_turn is None:
            from aryx.config import get_settings
            tier2_max_per_turn = get_settings().bml_tier2_max_per_turn
        self._tier2_cap = tier2_max_per_turn
        self._tier2_count = 0
        self._tier2_lock = threading.Lock()
        self._cap_warned = False
        self.stats = {
            "tier1": 0, "tier2": 0, "unknown": 0, "missing": 0, "cached": 0,
            "capped": 0, "durable_hit": 0,
            # docs/CPQ_Usage_Reporting_Gap — real token usage from every
            # Tier-2 LLM call this evaluator makes (hide/condition/values/
            # ask_worthy), accumulated across its whole lifetime (one
            # instance per turn, same scope as _tier2_count above). Every
            # _evaluate_llm_* method adds into these via _record_llm_usage
            # instead of discarding llm_runtime.chat's token counts —
            # previously silently thrown away (indexed [0] for text only),
            # so a turn with real Tier-2 activity still reported 0 tokens.
            "prompt_tokens": 0, "completion_tokens": 0,
        }

    def _record_llm_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Accumulate one Tier-2 LLM call's real token usage into self.stats.

        Called from every _evaluate_llm_* method right after a successful
        llm_runtime.chat call, regardless of whether the reply parsed to a
        usable result — the call itself happened and cost real tokens/
        latency either way, same as any other LLM call in this codebase.
        """
        self.stats["prompt_tokens"] += prompt_tokens
        self.stats["completion_tokens"] += completion_tokens

    def script_for(self, function_id: int) -> str | None:
        return self._scripts.get(function_id)

    def _prepare(
        self, kind: str, tier1_fn: Any, script: str, variables: dict[str, str],
        cache_id: int | None,
    ) -> tuple[tuple, Any, bool]:
        """Shared key/cache/Tier-1 step for hide_for_script/condition_holds/
        allowed_values_for_script (Amendment 18, docs/CPQ_UNIFIED_INTENT_
        CLASSIFIER_PLAN.md) — factored out so `prefetch_tier2` can run this
        same cheap, local, no-network step for a whole batch of scripts
        before deciding which ones genuinely need a Tier-2 call, without
        duplicating (and risking drift in) the cache-key formula each of
        those three methods already relied on individually.

        Returns (key, result, needs_tier2). When needs_tier2 is False,
        `result` is already final — a cache hit, a Tier-1 resolution, an
        unresolvable-due-to-missing-variable, or LLM disabled — and the
        caller should write it to the cache and return it directly, exactly
        as before this refactor. tier1_fn is evaluate_tier1 (allowed-values
        idiom) or evaluate_hide_tier1 (bool idiom, shared by hide_for_script
        and condition_holds) — both return (result, blocked_by_missing_var).
        """
        key = (kind, self._workspace_id, self._catalog_prefix,
               cache_id if cache_id is not None else hash(script),
               frozenset(variables.items()))
        if key in _SHARED_SCRIPT_CACHE:
            self.stats["cached"] += 1
            return key, _SHARED_SCRIPT_CACHE[key], False
        result, blocked_by_missing_var = tier1_fn(script, variables)
        if result is not None:
            self.stats["tier1"] += 1
            return key, result, False
        if blocked_by_missing_var:
            self.stats["unknown"] += 1
            return key, None, False
        if not self._use_llm:
            self.stats["unknown"] += 1
            return key, None, False
        if not self._reserve_tier2_slot():
            self.stats["capped"] += 1
            self.stats["unknown"] += 1
            return key, None, False
        return key, None, True

    def _reserve_tier2_slot(self) -> bool:
        """Claim one of this turn's Tier-2 attempts, or refuse once the cap
        (Amendment 18, `bml_tier2_max_per_turn`) is reached.

        Thread-safe (prefetch_tier2 dispatches from multiple threads at
        once) — a plain unguarded read-then-increment could let concurrent
        callers overshoot the cap. Logs a single warning the first time this
        turn hits the ceiling, so a truncated turn is visible in logs rather
        than silently incomplete.
        """
        with self._tier2_lock:
            if self._tier2_count >= self._tier2_cap:
                if not self._cap_warned:
                    self._cap_warned = True
                    logger.warning(
                        "bml: Tier-2 cap (%d) reached this turn (workspace=%s "
                        "catalog=%r) — further script-backed rules fall back "
                        "to 'unknown' (never guess) for the rest of this turn",
                        self._tier2_cap, self._workspace_id, self._catalog_prefix,
                    )
                return False
            self._tier2_count += 1
            return True

    def _store(self, key: tuple, result: Any) -> Any:
        """Write a final result to the shared cache (same cap-and-clear
        policy every call site already used) and return it, so both the
        single-script methods and prefetch_tier2's batch path share one
        write path."""
        if len(_SHARED_SCRIPT_CACHE) >= _MAX_SHARED_CACHE_ENTRIES:
            _SHARED_SCRIPT_CACHE.clear()
        _SHARED_SCRIPT_CACHE[key] = result
        return result

    def _durable_key(
        self, kind: str, script: str, variables: dict[str, str],
        cache_id: int | None,
    ) -> str:
        """Stable, cross-process cache key for the durable Tier-2 store
        (Amendment 18 option 4, docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md).

        Deliberately NOT Python's built-in hash() — string hashing is
        randomized per-process by default (PYTHONHASHSEED), so hash(script)
        (what the in-memory _SHARED_SCRIPT_CACHE key uses when cache_id is
        None) would compute a DIFFERENT value after every restart, making a
        durable store keyed on it a permanent, silent miss. sha256 over a
        canonical (sorted-keys JSON) representation is stable across
        processes, machines, and Python versions — the actual property this
        needs. Same identity components as the in-memory key (kind,
        workspace, catalog, script-or-cache_id, full variable state) — this
        durable layer changes WHERE a result is cached, never WHAT is
        treated as "the same state," so it carries no new correctness risk
        beyond the in-memory cache's own already-established semantics.
        """
        ident = cache_id if cache_id is not None else script
        canonical = json.dumps(
            {"kind": kind, "ws": self._workspace_id, "cat": self._catalog_prefix,
             "ident": ident, "vars": dict(sorted(variables.items()))},
            sort_keys=True, default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _durable_get(self, cache_key: str) -> tuple[Any, bool]:
        """Look up a Tier-2 result in the durable store. Returns (result,
        found) — best-effort: any DB error is treated as a miss, never
        raised, since this is a pure optimization layer over the same
        network-call fallback that already exists."""
        try:
            from aryx.config import get_settings
            from aryx.queries import load
            from aryx.store.pool import get_pool
            with get_pool(get_settings().effective_dsn()).connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(load("select_bml_tier2_cache"), (cache_key,))
                    row = cur.fetchone()
            if row is None:
                return None, False
            return json.loads(row[0]) if isinstance(row[0], str) else row[0], True
        except Exception:  # noqa: BLE001 — durable cache is best-effort only
            logger.debug("bml: durable tier-2 cache read failed", exc_info=True)
            return None, False

    def _durable_put(self, cache_key: str, kind: str, result: Any) -> None:
        """Persist a freshly-computed Tier-2 result. Best-effort: a write
        failure never blocks or fails the turn — the in-memory cache and
        the network fallback both still work exactly as before this layer
        existed."""
        try:
            from aryx.config import get_settings
            from aryx.queries import load
            from aryx.store.pool import get_pool
            with get_pool(get_settings().effective_dsn()).connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(load("upsert_bml_tier2_cache"), (
                        cache_key, self._workspace_id, kind, json.dumps(result),
                    ))
        except Exception:  # noqa: BLE001 — durable cache is best-effort only
            logger.debug("bml: durable tier-2 cache write failed", exc_info=True)

    def _call_tier2(
        self, kind: str, script: str, variables: dict[str, str],
        cache_id: int | None = None,
    ) -> Any:
        """Single entry point for every actual Tier-2 network call — checks
        the durable cross-process cache first, only calls the LLM on a
        genuine miss, then persists the fresh result. Replaces calling
        _evaluate_llm_hide/_evaluate_llm_condition/_evaluate_llm directly so
        all four Tier-2 call sites (hide_for_script, condition_holds,
        allowed_values_for_script, prefetch_tier2) get durability for free.
        """
        durable_key = self._durable_key(kind, script, variables, cache_id)
        result, found = self._durable_get(durable_key)
        if found:
            self.stats["durable_hit"] += 1
            return result
        result = {
            "hide": self._evaluate_llm_hide,
            "cond": self._evaluate_llm_condition,
            "values": self._evaluate_llm,
            "ask_worthy": self._evaluate_llm_ask_worthy,
        }[kind](script, dict(variables))
        self._durable_put(durable_key, kind, result)
        return result

    def classify_ask_worthy(
        self, attr_label: str, rule_message: str, rule_script: str, attr_key: int,
    ) -> bool:
        """Generic (not catalog-specific) Tier-2 judgment for a no-option,
        no-decision-keyword free-text attr that IS targeted by a
        ValidationRule: is this a value a sales rep configuring a quote
        would actively decide and enter, or an internal/advanced/system
        field the native UI doesn't normally prompt for?

        docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md Amendment 22 — every
        deterministic signal available (required flag, default_value,
        script shape, hiding-rule visibility) was confirmed identical
        between a genuine case (agencyDomainName_ID_swSoln,
        OfVideoStreamingDevices_3_swSoln) and a false-positive case
        (APX Next's systemID_astro / "Owner System ID", Amendment 20).
        Falls back to the LLM only because no cheaper signal exists —
        same escalation discipline as every other Tier-2 use in this file.
        Cached durably via the same `_call_tier2`/`aryx_bml_tier2_cache`
        machinery already used for script evaluation (kind="ask_worthy"),
        keyed by attr_key so it's a one-time cost per attribute, not per
        turn. Defaults to False (never guess toward asking) on any LLM
        failure or "unknown" — preserves the current safe/dormant
        behavior when the classifier can't decide.

        Routed through `_prepare` (Raven review, 2026-07-28) — previously
        called `_call_tier2` directly, which skipped BOTH the in-memory
        `_SHARED_SCRIPT_CACHE` check every other Tier-2 kind gets AND
        `bml_tier2_max_per_turn` (Amendment 18/PR #122) entirely, since only
        `_prepare` enforces that cap via `_reserve_tier2_slot()`. On an
        800+-attribute catalog with a cold durable cache, this reintroduced
        the exact unbounded-sequential-LLM-calls problem PR #122's cap
        exists to prevent. There's no Tier-1 idiom for "is this ask-worthy"
        (Amendment 22's whole premise is that no cheaper signal exists), so
        a tier1_fn that always defers to Tier-2 reuses `_prepare`'s cache/
        cap machinery without pretending a Tier-1 shortcut exists.
        """
        script = rule_script or ""
        # A gating condition (e.g. "only relevant when advancedFlag ==
        # YES") tends to sit in the script's FINAL return statement, not
        # its opening comments/setup — a head-only truncation can silently
        # cut it off on a long script (confirmed live: a 4407-char script
        # had its one gating clause at position 4315). Send both ends
        # rather than assume the interesting part is near the top.
        if len(script) > 4000:
            script = script[:2000] + "\n...\n" + script[-2000:]
        context = f"{attr_label}\n{rule_message or ''}\n{script}"
        key, result, needs_tier2 = self._prepare(
            "ask_worthy", lambda _s, _v: (None, False), context, {}, cache_id=attr_key)
        if needs_tier2:
            result = self._call_tier2("ask_worthy", context, {}, cache_id=attr_key)
            self.stats["tier2" if result is not None else "unknown"] += 1
        result = self._store(key, result)
        return bool(result) if isinstance(result, bool) else False

    def prefetch_tier2(
        self, requests: list[tuple[str, str, dict[str, str], int | None]],
    ) -> None:
        """Warm the shared cache for a batch of (kind, script, variables,
        cache_id) requests CONCURRENTLY, instead of the one-script-at-a-time
        sequential path every rule-application method otherwise takes.

        Amendment 18 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): a single
        turn on a large catalog can leave 800+ distinct scripts needing
        Tier-2 — live-confirmed sequential evaluation of that many scripts
        can take tens of minutes. Every script's evaluation is independent
        given a fixed variable-state snapshot, so this dispatches all of
        them at once via a thread pool (Tier-2 calls are blocking network
        I/O — urllib releases the GIL while waiting, so threads, not
        asyncio, parallelize this with no change to the existing synchronous
        call sites) and lets each one's result land in `_SHARED_SCRIPT_CACHE`
        under the EXACT same key `hide_for_script`/`condition_holds`/
        `allowed_values_for_script` would compute themselves. Those methods
        are NOT changed by this — they still run sequentially, in whatever
        order the existing apply_hiding_rules/apply_recommendation_rules/
        apply_constraint_rules loops call them — but every one of those
        calls becomes a cache hit instead of a fresh network round-trip.

        This method never raises and never changes behavior, only latency:
        a request this caller failed to include (or got a kind/script/
        variables slightly wrong for) simply doesn't get pre-warmed and
        falls through to the normal sequential path for that one script,
        exactly as if prefetch had never run at all.

        Deduplicates by cache key first (multiple rules can share the exact
        same script text and current variable state) so an identical
        Tier-2 call is never fired twice concurrently for the same answer.
        """
        tier1_fn = {
            "hide": evaluate_hide_tier1,
            "cond": evaluate_hide_tier1,
            "values": evaluate_tier1,
        }
        pending: dict[tuple, tuple[str, str, dict[str, str]]] = {}
        for kind, script, variables, cache_id in requests:
            fn = tier1_fn.get(kind)
            if fn is None:
                continue  # unrecognized kind — skip, never guess a mapping
            key, result, needs_tier2 = self._prepare(kind, fn, script, variables, cache_id)
            if needs_tier2:
                pending.setdefault(key, (kind, script, variables))
            else:
                self._store(key, result)
        if not pending:
            return

        def _run(item: tuple[tuple, tuple[str, str, dict[str, str]]]) -> None:
            key, (kind, script, variables) = item
            result = self._call_tier2(kind, script, variables)
            self.stats["tier2" if result is not None else "unknown"] += 1
            self._store(key, result)

        with ThreadPoolExecutor(max_workers=min(16, len(pending))) as pool:
            list(pool.map(_run, pending.items()))

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
        """Allowed-value list for a raw BML script body, or None if unknown.

        Cache key uses the FULL variable state, not a regex-filtered subset
        — live-confirmed bug: referenced_variables() can't see
        numeric-comparison/function-call variables (e.g. fmod(qty, 25)), so
        a key scoped to just those alone stayed IDENTICAL across genuinely
        different quantity values, and a cached True/False from one qty was
        wrongly reused for another. Key/cache/Tier-1 step factored into
        `_prepare` (Amendment 18) so `prefetch_tier2` can run the same cheap
        step for a whole batch before deciding what needs Tier 2 — this
        method's own behavior/return value is unchanged by that refactor.
        """
        key, result, needs_tier2 = self._prepare(
            "values", evaluate_tier1, script, variables, cache_id)
        if needs_tier2:
            # Full `variables`, not a regex-filtered subset — see
            # condition_holds' identical fix (docs/CPQ_UNIFIED_INTENT_
            # CLASSIFIER_PLAN.md Amendment 12/13 follow-up) for why:
            # referenced_variables() can't see numeric-comparison/
            # function-call variables, so a filtered subset can silently
            # omit the one variable a script actually depends on.
            result = self._call_tier2("values", script, variables, cache_id)
            self.stats["tier2" if result is not None else "unknown"] += 1
        return self._store(key, result)

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
            txt, _it, _ot = llm_runtime.chat("answer", sys_p, user_p)
            self._record_llm_usage(_it, _ot)
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
        constraint/recommendation allowed-values idiom. Key/cache/Tier-1 step
        factored into `_prepare` (Amendment 18) — see allowed_values_for_
        script's docstring; this method's own behavior is unchanged."""
        key, result, needs_tier2 = self._prepare(
            "hide", evaluate_hide_tier1, script, variables, cache_id)
        if needs_tier2:
            # Full `variables`, not a regex-filtered subset — same fix as
            # allowed_values_for_script/condition_holds.
            result = self._call_tier2("hide", script, variables, cache_id)
            self.stats["tier2" if result is not None else "unknown"] += 1
        return self._store(key, result)

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
            txt, _it, _ot = llm_runtime.chat("answer", sys_p, user_p)
            self._record_llm_usage(_it, _ot)
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
        (BM-native ids are only unique within one export, not globally).
        Key/cache/Tier-1 step factored into `_prepare` (Amendment 18) — see
        allowed_values_for_script's docstring; this method's own behavior
        is unchanged."""
        key, result, needs_tier2 = self._prepare(
            "cond", evaluate_hide_tier1, script, variables, cache_id)
        if needs_tier2:
            # Pass the FULL variables dict, not a regex-filtered subset —
            # live-confirmed: a script checking
            # `fmod(OfVideoStreamingDevices_3_swSoln, 25) <> 0` had that
            # exact variable silently excluded from a filtered subset,
            # leaving it unable to reason about the one variable the
            # condition actually depends on.
            result = self._call_tier2("cond", script, variables, cache_id)
            self.stats["tier2" if result is not None else "unknown"] += 1
        return self._store(key, result)

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
            txt, _it, _ot = llm_runtime.chat("answer", sys_p, user_p)
            self._record_llm_usage(_it, _ot)
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

    def _evaluate_llm_ask_worthy(
        self, context: str, variables: dict[str, str],
    ) -> bool | None:
        """Tier 2: ask the reason model whether a no-option, validation-rule
        -governed free-text attribute is worth proactively asking a sales
        rep about (see classify_ask_worthy above). `variables` is unused —
        this is a static per-attribute judgment, not a per-turn one; kept
        only to match _call_tier2's shared dispatch signature.
        """
        try:
            from aryx import llm_runtime
            sys_p = (
                "You classify BigMachines CPQ configuration attributes. "
                "Given an attribute's display label and its validation "
                "rule's message/script, decide whether a sales rep "
                "configuring a customer quote would need to actively "
                "decide and enter this value (a genuine quote-relevant "
                "decision, e.g. a quantity, domain name, or setting the "
                "customer cares about), versus an internal, advanced, or "
                "system-integration field the native UI would not "
                "normally prompt a rep for.\n\n"
                "Read the FULL script, not just the label — it often "
                "contains the real signal. If the script's condition only "
                "matters when ANOTHER attribute (not this one) is set to "
                "an enabling/advanced value (e.g. an '...advanced...', "
                "'...key...', or similar toggle-style attribute name "
                "equals YES/enabled), that is a strong sign this is a "
                "conditional, advanced, or hardware-integration field a "
                "rep would not be asked about by default — answer false "
                "unless the label itself is unambiguously a core, always-"
                "relevant business fact (e.g. a domain name, a device "
                "count, a service duration)."
            )
            user_p = (
                f"Attribute label and validation rule context:\n{context[:4600]}\n\n"
                'Reply ONLY as JSON: {"ask_worthy": true} or '
                '{"ask_worthy": false} or {"unknown": true} if it cannot '
                "be determined."
            )
            txt, _it, _ot = llm_runtime.chat("answer", sys_p, user_p)
            self._record_llm_usage(_it, _ot)
            s, e = txt.find("{"), txt.rfind("}")
            if s == -1 or e <= s:
                return None
            d = json.loads(txt[s:e + 1])
            if d.get("unknown"):
                return None
            val = d.get("ask_worthy")
            if isinstance(val, bool):
                return val
        except Exception:  # noqa: BLE001 — LLM unavailable → unknown, not fatal
            logger.debug("bml: tier-2 LLM ask-worthy classification failed", exc_info=True)
        return None
