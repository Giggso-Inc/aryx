"""Question/option-text normalization helpers for catalog-hint matching,
split out of `cpq/engine.py`'s module-level scope (Phase 4, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md -- module-level helper extraction
beyond the 8 previously-deferred methods, done purely to shrink engine.py
further). Re-exported from `aryx.cpq.engine` (see the import there) so
every existing `from aryx.cpq.engine import <name>` caller/test -- and
`_engine_module.<name>(...)`'s whole-module-reference calls in
`catalog_hints.py`/`catalog_hints_negation.py` -- keep working unchanged.
Logic unchanged from the original inline definitions.
"""

from __future__ import annotations

import re

from aryx.cpq.engine import _HINT_MIN_PHRASE_LEN, _HINT_STRIP_RE


def _parenthetical_suffix(text: str) -> str | None:
    """The content of a trailing "(...)" segment in `text`, or None.

    Catalog display names often encode a distinguishing variant this way —
    "APX NEXT (4G LTE+5G)": a common family name outside the parens, the
    specific variant inside. extract_catalog_hints' D2 verbatim rule
    requires the WHOLE glued option text to appear in the question; a
    customer answering with only the variant ("I'll take the 4G LTE+5G
    version") — the most natural way to name it — never satisfies that,
    even though the variant is exactly what distinguishes this option from
    its siblings. Exposing the inner segment as an additional candidate
    text lets the existing ambiguity/negation/never-guess machinery in
    extract_catalog_hints treat it exactly like any other option text —
    this is plain string parsing (no pattern list, no per-product
    special-casing), so it generalizes to any catalog option shaped this
    way, not just this one product.

    Only a single, unnested trailing "(...)" is trusted — returns None on
    anything else (nested parens, an unmatched "(" earlier in the segment,
    empty parens), so a shape this helper can't safely parse is simply
    never offered as a candidate rather than risk extracting a corrupted
    fragment (e.g. a literal trailing ")" left over from a nested group).
    """
    stripped = text.rstrip()
    if "(" not in stripped or not stripped.endswith(")"):
        return None
    _before, _, after = stripped.rpartition("(")
    inner = after[:-1].strip()
    if "(" in inner or ")" in inner:
        return None
    return inner or None


def _normalize_for_hint(text: str) -> str:
    return _HINT_STRIP_RE.sub("", text.lower())


def _normalize_for_hint_with_map(text: str) -> tuple[str, list[int]]:
    """Same stripping as _normalize_for_hint, but also returns index_map
    where index_map[i] is the original `text` position that the i-th
    character of the normalized string came from — lets a match found in
    the glued/stripped string be traced back to its real location, e.g. to
    inspect the words that precede it (see _is_negated_before)."""
    lowered = text.lower()
    kept: list[str] = []
    index_map: list[int] = []
    for i, ch in enumerate(lowered):
        if ch.isalnum():
            kept.append(ch)
            index_map.append(i)
    return "".join(kept), index_map


# Cue words that flip a literal option-text match into an exclusion rather
# than a selection — "exclude any... carry solutions" contains the exact
# text of the real option "Carry Solutions", but means the opposite
# (confirmed live: accessoriesSolutionSet_astro was auto-filled to "CARRY
# SOLUTIONS" from that sentence). Word-bounded so short cues ("no", "not")
# don't fire inside unrelated words ("know", "notification").
_NEGATION_RE = re.compile(
    r"\b(exclud\w*|without|no|not|never|omit\w*|remov\w*|minus)\b",
    re.IGNORECASE,
)
_NEGATION_WINDOW_CHARS = 40


def _is_negated_before(question_lower: str, orig_pos: int) -> bool:
    window_start = max(0, orig_pos - _NEGATION_WINDOW_CHARS)
    return bool(_NEGATION_RE.search(question_lower[window_start:orig_pos]))


def _find_plural_tolerant(q_norm: str, phrase: str) -> int:
    """q_norm.find(phrase), tolerating a missing/extra trailing "s".

    Confirmed live: option text "CARRY SOLUTIONS" (normalized
    "carrysolutions") never matched a customer writing "no carry solution"
    (singular) — an exact-substring search on "carrysolution" fails against
    "carrysolutions" by exactly one character, so the negation guard never
    saw it and accessoriesSolutionSet_astro was silently auto-filled with
    the very thing the customer excluded. Trying the phrase with its
    trailing "s" added/removed catches this without weakening the
    real length/ambiguity guards elsewhere (this only changes WHERE a
    phrase is found in the question, not which attrs are eligible).
    """
    idx = q_norm.find(phrase)
    if idx != -1:
        return idx
    variant = phrase[:-1] if phrase.endswith("s") else phrase + "s"
    if len(variant) < _HINT_MIN_PHRASE_LEN:
        return -1
    return q_norm.find(variant)
