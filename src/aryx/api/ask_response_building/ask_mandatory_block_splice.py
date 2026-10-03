"""Deduplicating and splicing Beautify's "Mandatory User Input" block
into the conversational summary, split out of `ask_api.py` (final
sweep, Phase 11/11-phase ask_api decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md — PR #236). Whatever Beautify's own
Mandatory User Input section shows must be the SAME set shown under the
conversational summary's own heading — verbatim, not the narrower
subset the summary's own category grouping would otherwise leave there.
`_labels_already_shown`/`_beautify_mandatory_block` dedupe against
whatever Product Name/Service Plan/Quantity & Duration already rendered
above it, keying on the (label, value) pair (not label alone) since
`beautify_rows` carries no attribute identifier to key on instead.
`_splice_mandatory_block_into_summary` forces the chat answer's own
section to be a byte-for-byte copy of the Beautify rows, fenced as a
code block to preserve column alignment. Logic unchanged from the
original inline definitions.
"""

from __future__ import annotations

import re

from aryx.cpq.engine import CpqEngine, SUMMARY_CATEGORY_NAMES, SUMMARY_FALLBACK_CATEGORY
from aryx.raven_log import raven_log

_SHARE_READY_MIN_FILLED = 3

# The closed set of "**Category:**" headers the summary's own category
# grouping (categorized_summary_groups/_SUMMARY_CATEGORY_KEYS) can ever
# emit, OTHER than Mandatory User Input itself. Raven review on PR #236
# (H2): the original boundary regex treated ANY bold, colon-terminated
# line as "the next category header" -- safe against beautify_text()'s
# own trusted, machine-generated output, but not against free-form LLM
# narration, where a stray aside like "**Note:**" inside the Mandatory
# section's own body would be misread as a header and truncate the
# match early. Anchoring to this known, closed set (plus the literal
# Mandatory User Input header) means only a REAL category boundary ever
# stops the match, regardless of what the LLM narrates around it.
#
# Derived from `SUMMARY_CATEGORY_NAMES`/`SUMMARY_FALLBACK_CATEGORY` (PR
# #236 review, Medium follow-up) rather than duplicated as hardcoded
# string literals here -- a renamed or newly-added category in engine.py
# now updates this boundary automatically instead of silently
# under-matching again until someone remembers to edit a second copy.
_OTHER_SUMMARY_CATEGORY_HEADERS = SUMMARY_CATEGORY_NAMES + (SUMMARY_FALLBACK_CATEGORY,)

# Trailing call-to-action the deterministic/LLM-narrated summary appends
# after every category. Matched with flexible leading whitespace (PR #236
# C1): the original pattern only recognized this trailer when preceded by
# exactly "\n\n" -- any other whitespace (single newline, none, reordered
# trailing content) meant NONE of the lookahead alternatives fired before
# end-of-string, so the non-greedy body match was forced all the way to
# \Z, silently deleting the trailer along with whatever it replaced.
_CPQ_JSON_TRAILER_RE = re.compile(r"\n*Click \*\*JSON\*\*")

_MANDATORY_HEADER = f"**{CpqEngine._BEAUTIFY_MANDATORY_SECTION}:**"
# Matches the header (tolerant of stray trailing whitespace before its
# newline, PR #236 C2) plus everything up to the next known category
# header, the JSON trailer, or end of string -- used for BOTH detecting
# whether a Mandatory User Input section already exists and replacing it,
# so the two checks can never disagree.
_MANDATORY_SECTION_RE = re.compile(
    re.escape(_MANDATORY_HEADER) + r"[ \t]*\n.*?"
    r"(?=\n\*\*(?:" + "|".join(re.escape(c) for c in _OTHER_SUMMARY_CATEGORY_HEADERS) + r"):\*\*"
    r"|\n*Click \*\*JSON\*\*|\Z)",
    re.DOTALL,
)

# A narrower "- **Label** → value" bullet, as rendered by the LLM-narrated
# or deterministic Product Name/Service Plan/Quantity & Duration
# categories. Requiring the VALUE to match too (not label alone) makes an
# incorrect exclusion vanishingly unlikely — two unrelated attributes
# coincidentally sharing both the same label and the same value.
_NAMED_CATEGORY_BULLET_RE = re.compile(r"^-\s+\*\*([^*\n]+)\*\*\s*→\s*(.+)$", re.MULTILINE)


def _labels_already_shown(answer: str) -> set[tuple[str, str]]:
    """(label, value) pairs already rendered as their own bullet somewhere
    before the Mandatory User Input header — both case-folded for a
    tolerant compare against Beautify's row labels/values."""
    idx = answer.find(_MANDATORY_HEADER)
    prefix = answer[:idx] if idx != -1 else answer
    return {
        (m.group(1).strip().casefold(), m.group(2).strip().casefold())
        for m in _NAMED_CATEGORY_BULLET_RE.finditer(prefix)
    }


def _beautify_mandatory_block(
    beautify_rows: list[dict[str, str]], already_shown: set[tuple[str, str]],
) -> str | None:
    """Return an aligned "Label : Value" block built from `beautify_
    rows`'s Mandatory User Input rows, excluding any row whose (label,
    value) the summary already rendered under a named category. Returns
    `None` when there's nothing left to show.
    """
    rows = [
        r for r in beautify_rows
        if r.get("section") == CpqEngine._BEAUTIFY_MANDATORY_SECTION
        and (r.get("label", "").strip().casefold(), r.get("value", "").strip().casefold())
        not in already_shown
    ]
    raven_log("DEBUG", "P4", "ask.response.mandatory_block built from beautify rows", context={
        "selected_option": "block" if rows else "none", "available_options": ["block", "none"],
        "reason_code": "MANDATORY_ROWS_REMAIN" if rows else "NO_UNSHOWN_MANDATORY_ROWS",
        "beautify_row_count": len(beautify_rows), "already_shown_count": len(already_shown),
        "mandatory_row_count": len(rows)})
    if not rows:
        return None
    width = max(len(r["label"]) for r in rows)
    return "\n".join(f"{r['label'].ljust(width)} : {r['value']}" for r in rows)


def _splice_mandatory_block_into_summary(answer: str, mandatory_block: str) -> str:
    """Forces the chat answer's own Mandatory User Input section to be a
    byte-for-byte copy of the (already-deduplicated) Beautify rows,
    fenced as a code block to preserve column alignment. Replaces an
    existing section up to the next known category header or the
    trailing "Click **JSON**..." sentence; if the answer has no such
    section, inserts one before the JSON trailer instead.
    """
    fenced = f"{_MANDATORY_HEADER}\n```\n{mandatory_block}\n```"
    new_answer, count = _MANDATORY_SECTION_RE.subn(fenced, answer, count=1)
    trailer_match = None if count else _CPQ_JSON_TRAILER_RE.search(answer)
    _opt = "replace_section" if count else ("insert_before_trailer" if trailer_match else "append")
    raven_log("DEBUG", "P4", "ask.response.mandatory_splice placed mandatory block", context={
        "selected_option": _opt, "available_options": ["replace_section", "insert_before_trailer", "append"],
        "reason_code": {"replace_section": "SECTION_FOUND", "insert_before_trailer": "TRAILER_FOUND",
                        "append": "NO_SECTION_NO_TRAILER"}[_opt],
        "answer_len": len(answer), "block_line_count": mandatory_block.count("\n") + 1})
    if count:
        return new_answer
    if trailer_match:
        before = answer[:trailer_match.start()].rstrip()
        after = answer[trailer_match.start():].lstrip("\n")
        return f"{before}\n\n{fenced}\n\n{after}"
    return f"{answer.rstrip()}\n\n{fenced}"
