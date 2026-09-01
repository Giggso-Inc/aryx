"""Replacement clause extraction — wanted vs rejected values.

PROMPT 6 / reversed-cue fix. Design (a) pattern-first: try explicit
contrast-first forms BEFORE the leftmost-cue path. Cue vocabulary
(use|instead|prefer|rather) overlaps contrast vocabulary (instead of|
rather than|not), so position-only assignment silently flips roles on
English mirror forms ("instead of Standard, prefer Premium").

Follow-up (b): piggyback wanted/rejected on the intent-gateway schema
once that path is already one LLM call/turn.

Prior rounds: leftmost cue (§12), trailing contrast cut (§15). This
round adds reversed contrast-first + of-remnant belt-and-braces.

Kept free of FastAPI / engine imports so offline regression can load it.
"""
from __future__ import annotations

import re

_REPLACEMENT_CUE_RE = re.compile(
    r"\b(?:use|instead|prefer|rather|choose|go\s+with)\b\s*[:,]?\s*(.+)$",
    re.IGNORECASE,
)
_CONTRAST_CUT_RE = re.compile(
    r"\b(?:over|than|instead\s+of|rather\s+than|not)\b",
    re.IGNORECASE,
)
# "instead of Standard, prefer Premium" / "rather than X, use Y" /
# "not Standard — Premium" / "not Standard, Premium please"
_REVERSED_CONTRAST_FIRST_RE = re.compile(
    r"^(?:instead\s+of|rather\s+than|not)\s+(?P<rejected>.+?)"
    r"[,;—–-]+\s*"
    r"(?:(?:please\s+)?(?:use|prefer|choose|go\s+with|rather)\s+)?"
    r"(?P<wanted>.+)$",
    re.IGNORECASE,
)
# Same without punctuation, but second cue word is required so we don't
# swallow "instead of Standard Premium Extra" ambiguously.
_REVERSED_CONTRAST_CUE_RE = re.compile(
    r"^(?:instead\s+of|rather\s+than)\s+(?P<rejected>.+?)\s+"
    r"(?:use|prefer|choose|go\s+with|rather)\s+(?P<wanted>.+)$",
    re.IGNORECASE,
)
# After leftmost cue ate the "instead" half of "instead of …":
# capture becomes "of Standard, prefer Premium".
_LEADING_OF_REMNANT_RE = re.compile(
    r"^of\s+(?P<rejected>.+?)[,;—–-]+\s*"
    r"(?:(?:please\s+)?(?:use|prefer|choose|go\s+with|rather)\s+)?"
    r"(?P<wanted>.+)$",
    re.IGNORECASE,
)
_TRAILING_PLEASE_RE = re.compile(r"\bplease\b\.?\s*$", re.IGNORECASE)


def clean_clause_fragment(text: str) -> str:
    """Trim punctuation / trailing please from a wanted or rejected fragment."""
    cleaned = (text or "").strip(" \t.,;:!?")
    cleaned = _TRAILING_PLEASE_RE.sub("", cleaned).strip(" \t.,;:!?")
    return cleaned


def extract_replacement_clause(text: str) -> tuple[str | None, str | None]:
    """Extract (wanted_clause, rejected_clause) from a replacement phrasing.

    Returns (None, None) when no replacement cue/contrast form is present
    — callers should fall back to the full message. When a form is
    recognized, ``wanted`` never contains the rejected value string
    (asserted by unit tests). ``rejected`` may be None on pure "use Premium"
    cues.
    """
    raw = (text or "").strip()
    if not raw:
        return None, None

    # 1) Contrast-first reversed forms (tried BEFORE leftmost cue).
    for pat in (_REVERSED_CONTRAST_FIRST_RE, _REVERSED_CONTRAST_CUE_RE):
        m = pat.match(raw)
        if not m:
            continue
        wanted = clean_clause_fragment(m.group("wanted"))
        rejected = clean_clause_fragment(m.group("rejected"))
        if wanted:
            return wanted, (rejected or None)

    # 2) Leftmost-cue path (forward forms + remnant guard).
    m = _REPLACEMENT_CUE_RE.search(raw)
    if not m or not m.group(1).strip():
        return None, None
    clause = m.group(1).strip()

    of_rem = _LEADING_OF_REMNANT_RE.match(clause)
    if of_rem:
        wanted = clean_clause_fragment(of_rem.group("wanted"))
        rejected = clean_clause_fragment(of_rem.group("rejected"))
        if wanted:
            return wanted, (rejected or None)

    rejected: str | None = None
    cut = _CONTRAST_CUT_RE.search(clause)
    if cut:
        rejected = clean_clause_fragment(clause[cut.end():]) or None
        clause = clause[:cut.start()].strip()
    wanted = clean_clause_fragment(clause)
    if not wanted:
        return None, rejected
    return wanted, rejected
