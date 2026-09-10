"""Turn-intent regex/constant patterns cluster, part 2 (Phase 4 step 2
extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Attr-activation/clear/bulk-quantity/decline/summary patterns plus the
small shared constants -- split from ``patterns.py`` purely to keep both
files under the file-size cap; no thematic distinction beyond that.
"""

from __future__ import annotations

import re

# "add/activate/include/bring back/turn on X" — re-activating a real,
# currently-excluded, optional catalog attr post-quote-generation
# (docs/CPQ_POST_QUOTE_EDIT_AND_QA_PLAN.md D2). Deliberately distinct
# from _CHANGE_VERB_RE: "change X to Y" replaces an already-visible
# attr's value, while "add X" re-activates something not currently
# part of the quote at all.
_ADD_VERB_RE = re.compile(
    r"\b(add|activate|include|bring\s+back|re-?add|reactivate|turn\s+on)\b",
    re.IGNORECASE,
)

# "clear/unset/blank X" — nullifying an optional SINGLE-select attr's
# current value back to empty (D4). Distinct from _REMOVE_VERB_RE
# (multi-select deselection, a different data structure entirely) and
# from _CHANGE_VERB_RE (replacing with a different concrete value).
_CLEAR_VERB_RE = re.compile(
    r"\b(clear|unset|blank|leave\s+(?:it\s+)?(?:blank|empty|unset))\b",
    re.IGNORECASE,
)

# "change/set/update/make ... quantit(y|ies) ... to <number>" OR
# "change/set/... both/all/every ... to <number>" — a bulk per-row
# quantity update, distinct from _CHANGE_VERB_RE's single-attribute
# value change. Live-verified gap (2026-07-22): "change both the
# mounting type to 25" — no "quantity" word at all, just "both" —
# missed the original quantity-only regex and fell into
# detect_change_request_collision instead, where 25 (never a real
# mount option) couldn't resolve either. The "both/all/every" branch
# is intentionally broader; detect_bulk_quantity_change's own
# restriction to resolve_array_grid_links' selectors with actually
# resolvable selected rows is the real safety net, not this regex.
_BULK_QTY_RE = re.compile(
    r"\b(?:change|set|update|make)\b.{0,80}"
    r"\b(?:quantit(?:y|ies)|both|all|every)\b.{0,60}"
    r"\bto\b\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE | re.DOTALL,
)

# Decline keywords — user is explicitly rejecting the awaiting-approval
# configuration (ISSUE-002, docs/CPQ_E2E_ISSUES_001_002_003_004_FIX_
# PLAN_2026_08_17.md). Anchored at the start of the message exactly like
# _APPROVAL_RE above, deliberately NOT a bare substring search — a
# substring match on "no" would false-positive on ordinary attribute
# answers that happen to start with a negative word (e.g. "no carry
# solution" as a value), which this detector must never be consulted
# for anyway (callers only invoke it in awaiting-approval-adjacent
# dispatch), but the anchored shape keeps the regex itself conservative
# regardless of call site.
_DECLINE_RE = re.compile(
    r"^no+\b[\s,!.]*$|"  # bare "no"/"noo" (optionally with trailing punctuation) alone
    r"^(?:no+\b[\s,!.]*)?"
    r"(?:i\s+(?:hereby\s+|just\s+|really\s+)?)?"
    r"(nope|declin(?:e|ed|ing)|reject(?:ed|ing)?|cancel(?:led|ing)?|"
    r"don'?t\s+(?:approve|submit|confirm|finali[sz]e|send\s+it|go\s+ahead)|"
    r"do\s+not\s+(?:approve|submit|confirm|finali[sz]e|send\s+it|go\s+ahead)|"
    r"not\s+(?:yet|now|ready)|hold\s+on|wait|"
    r"that'?s?\s+(?:wrong|not\s+(?:right|correct))|go\s+back)\b",
    re.IGNORECASE,
)

# "give/show me the (final) summary/configuration", "recap", "what do
# I have so far" — a request to RE-SHOW the current configuration, not
# a question about a specific attribute and not an approval. Live-
# verified gap, 2026-08-13: with no dedicated category for this, "give
# the final summary now" was classified OUT_OF_SCOPE by the LLM
# classifier (none of its fixed categories represent "show it again"),
# and a shorter phrasing like "give the configuration" could
# coincidentally word-match a real catalog attribute whose own label
# contains "configuration" (e.g. "Configuration Type"), silently
# hijacking the turn into a change-target prompt for that unrelated
# attribute instead. Checked deterministically, ahead of both paths.
_SHOW_SUMMARY_RE = re.compile(
    r"(?i:"
    r"\b(?:show|give|send|display)\s+(?:me\s+)?(?:the\s+)?"
    r"(?:final\s+|current\s+|full\s+)?(?:summary|configuration|config)\b"
    r"|\brecap\b"
    r"|\breview\s+(?:the\s+|my\s+)?(?:configuration|config|summary|order)\b"
    r"|\bwhat\s+(?:do\s+i\s+have|have\s+i\s+(?:chosen|selected|picked))\s+so\s+far\b"
    r"|\bwhat'?s?\s+my\s+(?:current\s+)?(?:configuration|config)\b"
    r")"
)

# Cap on detect_change_requests_multi's result — a message naming more
# than this is unusual enough that blindly trusting every match risks
# silently misapplying something the user didn't actually intend
# (product decision: cap 3, apply whichever parse, report the rest).
_MAX_MULTI_CHANGE_REQUESTS = 3

# Generic connector/control words a leftover clause commonly contains
# that are never themselves part of a real catalog label — excluded so
# e.g. "...and confirm" doesn't count "confirm" as catalog-word overlap
# just because some unrelated attr's label happens to share it.
_GENERIC_CLAUSE_STOPWORDS = frozenset({
    "to", "the", "a", "an", "then", "please", "also", "and", "or",
    "change", "set", "update", "make", "it", "that", "this", "for",
    "with", "of", "in", "on", "confirm", "submit", "thanks", "thank",
    "yes", "no", "ok", "okay", "done",
})

# ── Attribute option query detection ─────────────────────────────────────

_OPTIONS_KEYWORDS: frozenset[str] = frozenset({
    "values", "options", "available", "what are", "list", "choices",
    "show me", "which", "can i choose", "what can",
})

# Recognizes the recurring `allowedChars = "..."` character-allowlist
# idiom in ValidationRule condition_scripts (confirmed live in both the
# CC Aware 2026 and CC Aware "Allow only specific characters on PD
# AGDOMAIN" rules) — the only script shape this describes; anything else
# returns None rather than guessing at a description.
_ALLOWED_CHARS_RE = re.compile(r'allowedChars\s*=\s*"([^"]*)"')
