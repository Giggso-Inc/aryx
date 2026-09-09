"""Deterministic plain-language target_description resolution against a
real catalog attr, split out of `api/ask_api.py` (Phase 4/11-phase
ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Logic unchanged from the original inline definition.
"""

from __future__ import annotations

import re
from typing import Any

_WORD_RE = re.compile(r"[a-z0-9]+")


def _resolve_target_description(
    description: str, attrs: list,
) -> "tuple[Any | None, list[Any]]":
    """Resolve a plain-language target_description to a real catalog attr —
    the deterministic "exactness" layer the LLM-first design (plan doc §5)
    relies on.

    NOT built on `_relevant_intent_candidates` — live-confirmed bug during
    Phase 2 validation: that function returns the top-K (K=10) candidates
    by score, not just the tied-best ones, so it almost always returns
    2+ candidates whenever ANY word overlaps at all (its actual job —
    narrowing an LLM prompt's candidate list — never needed a single
    winner). Reusing it here made every resolution attempt look
    "ambiguous" even for an attr with a genuinely unique label. This
    scores every attr directly against display_label + option display
    names and only resolves when there is a single STRICTLY-highest-
    scoring attr with a nonzero score — a tie at the top, or zero
    overlap, both mean "unresolved."

    Scoring is rarity-weighted (1/document_frequency per matched word,
    same fix applied to `_relevant_intent_candidates` for the identical
    bug): live-confirmed during Phase 2 validation that raw overlap
    COUNT ties a distinctive word ("solution") together with a generic
    word shared by dozens of attrs' labels/options ("type"), so e.g.
    "Solution Type" (which should uniquely score highest against
    `solutionTypeDevices_astro`, matching BOTH words) instead tied with
    ~50 unrelated Type-suffixed attrs that only matched "type" — because
    a raw count of 1 look identical to another count of 1 regardless of
    how common the matched word is catalog-wide. Rarity weighting makes
    a match on a rare word worth far more than a match on a word present
    in every third attr's option list.

    Returns (resolved_attr, all_candidates_with_nonzero_overlap).
    `resolved_attr` is None whenever resolution didn't narrow to exactly
    one clear winner — logged/handled as unresolved by the caller, never
    silently guessed at (plan doc mitigation #1/#4: this is precisely
    where a hallucinated-but-plausible target must be caught, not passed
    through).
    """
    d_words = set(_WORD_RE.findall(description.lower()))
    if not d_words:
        return None, []
    vocabs = []
    for a in attrs:
        vocab = set(_WORD_RE.findall(a.display_label.lower()))
        for o in a.options:
            vocab |= set(_WORD_RE.findall(o.display_name.lower()))
        vocabs.append(vocab)
    doc_freq: dict[str, int] = {}
    for vocab in vocabs:
        for w in vocab:
            doc_freq[w] = doc_freq.get(w, 0) + 1
    scored = []
    for a, vocab in zip(attrs, vocabs):
        overlap_words = d_words & vocab
        if overlap_words:
            score = sum(1.0 / doc_freq[w] for w in overlap_words)
            scored.append((score, a))
    if not scored:
        return None, []
    scored.sort(key=lambda pair: pair[0], reverse=True)
    candidates = [a for _score, a in scored]
    if len(scored) == 1 or scored[0][0] > scored[1][0]:
        return scored[0][1], candidates
    return None, candidates
