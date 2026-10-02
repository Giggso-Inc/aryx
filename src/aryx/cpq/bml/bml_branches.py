"""Branch (if/else-if/else chain) parsing + allowed-value/bool extraction
for Tier-1 BML evaluation.

Split out of `cpq/bml.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See `bml_text.py`'s docstring for the zero-patch-risk basis --
confirmed here too: `test_cpq_bml_bool_literal_and_return_string.py`
imports `_parse_branches`/`_branch_values` directly (no patch), which the
re-export from `cpq/bml.py` continues to serve unchanged.
"""
from __future__ import annotations

import logging
import re

from aryx.config import get_settings
from aryx.cpq.bml.bml_conditions import _parse_boolean_expr, _parse_condition
from aryx.cpq.bml.bml_text import _find_block, _strip_block_comments, _strip_line_comments

logger = logging.getLogger(__name__)


# returnVal = "A"|"B"|... assignment inside a branch body. Also matches
# `retVal = ...` (no "urn") — confirmed live: dozens of real APX NEXT
# constraint/recommendation scripts (docs/CPQ_APX_NEXT_RULE_CATALOG.md) use
# "retVal" interchangeably with "returnVal"; the old pattern required the
# literal substring "return", which "retVal" doesn't contain at all, so
# every such script silently fell through to Tier 2 instead of Tier 1.
_ASSIGN_RE = re.compile(r're(?:t|turn)[Vv]al\s*=\s*((?:"[^"]*"\s*(?:\|\s*)?)+);?')
_STR_RE = re.compile(r'"([^"]*)"')

# ANY_IDENTIFIER = string[]{ "A", "B", "C" }; — a branch reassigning some
# arbitrary local variable (not necessarily returnVal/retVal — confirmed
# live: real SVX Mounting Type (Array) narrowing script uses `ret`) to a
# comma-separated array literal, returned by reference elsewhere in the
# script (`return ret;`, outside the if/else _parse_branches only hands
# this function the matched branch's OWN body for — the trailing return
# is never part of `body` at all). Distinct idiom from `_ASSIGN_RE`'s
# pipe-delimited `returnVal = "A"|"B"` shape: comma-separated inside a
# `string[]{...}` constructor, any variable name. Confirmed live this is
# exactly what left a real narrowing rule inert (evaluate_tier1 always
# returned (None, False) for it) even though its condition parsed and
# matched correctly — this deployment's Tier-2 LLM fallback then also
# failed to resolve it, so the customer-facing option list stayed at the
# raw, unfiltered 12-option catalog menu instead of the narrowed 5/6.
_ARRAY_LITERAL_ASSIGN_RE = re.compile(
    r'\w+\s*=\s*string\s*\[\s*\]\s*\{([^{}]*)\}\s*;?', re.IGNORECASE)

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

_BARE_RETURN_RE = re.compile(r'\A\s*return\s+.+?;\s*\Z', re.IGNORECASE | re.DOTALL)


def _parse_branches(script: str) -> list[tuple[list | "_BoolExpr" | None, str]] | None:
    """Parse an if / else-if / else chain into [(condition, body)].

    condition is _parse_condition's flat-list output, a _BoolExpr (only for
    a condition that mixed AND/OR and needed the separate recursive parser —
    docs/CPQ_TIER1_MIXED_AND_OR_CONDITION_PARSER_PLAN_2026_08_10.md), or None
    for the else branch. Returns None when the script doesn't fit the Tier-1
    idiom at all.
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
            # docs/CPQ_TIER1_MIXED_AND_OR_CONDITION_PARSER_PLAN_2026_08_10.md
            # -- fallback only: _parse_condition requires a UNIFORM AND-only
            # or OR-only chain and returns None for a mixed condition (e.g.
            # `(A OR B OR C) AND D`). Every condition _parse_condition
            # already resolves never reaches this line.
            cond = _parse_boolean_expr(cond_text)
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
    split_tilde = get_settings().cpq_bml_tilde_split_enabled
    out: list[str] = []
    for v in values:
        parts = v.split("|^|") if "|^|" in v else [v]
        for part in parts:
            if split_tilde and "~" in part.replace("\\~", ""):
                # `~` is the catalog's other multi-value packing convention
                # (aryxent PR 12), e.g. "A~B~C" -- gated, off by default.
                # A literal tilde is written `\~` and never splits.
                out.extend(
                    sub.replace("\\~", "~").strip()
                    for sub in re.split(r"(?<!\\)~", part) if sub.strip()
                )
            elif split_tilde and "\\~" in part:
                out.append(part.replace("\\~", "~").strip())
            elif "|^|" in v:
                if part.strip():
                    out.append(part.strip())
            elif part:
                out.append(part)
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
    _arr_matches = list(_ARRAY_LITERAL_ASSIGN_RE.finditer(body))
    if _arr_matches:
        # `VAR = string[]{"A","B","C"};` — comma-separated, any variable
        # name, distinct idiom from the pipe-delimited returnVal/retVal
        # assignment below. Raven review (PR #269): the branch's own
        # trailing `return VAR;` is never part of `body` at all (see
        # _parse_branches), so which assignment is "the one that counts"
        # can't be resolved by name — the LAST array-literal assignment in
        # source order wins, matching evaluate_constant_return's own
        # `_LOCAL_LITERAL_ASSIGN_RE` precedent for this exact "multiple
        # assignments, which one counts" ambiguity (normal execution
        # order: a later reassignment always shadows an earlier one).
        # Confirmed live this is the correct real-world case too: the
        # real SVX script's own `ret = string[];` placeholder sits BEFORE
        # the if/else entirely (outside every branch body), so a real
        # branch only ever contains its own single, final assignment.
        return [v for v in _STR_RE.findall(_arr_matches[-1].group(1)) if v]
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
