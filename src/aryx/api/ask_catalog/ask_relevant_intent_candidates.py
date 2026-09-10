"""Narrowing a candidate attr list to the ones a question is plausibly
about, by rarity-weighted word overlap, split out of `api/ask_api.py`
(Phase 6/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md). Logic unchanged from the original inline
definition.
"""

from __future__ import annotations

import re

_LLM_INTENT_ATTRS_CAP_HARD = 500  # safety bound on relevance-scoring work, not a relevance cutoff
_LLM_INTENT_RELEVANT_CAP = 10
_WORD_RE = re.compile(r"[a-z0-9]+")


def _relevant_intent_candidates(
    question: str, candidates: list, fallback_to_full: bool = True,
) -> list:
    """Narrow the candidate list to the attrs the question is actually
    plausibly about, by simple word overlap against display_label and
    option display names.

    Live-verified need (2026-07-22): handing the full ~40-attr candidate
    list to the classifier — even one restricted to filled attrs — diluted
    the signal enough that a phrase the model correctly classified in
    isolation came back "none" once real catalog noise was mixed in.
    Keeping only the attrs whose own vocabulary overlaps the question
    keeps the prompt small and on-topic; falls back to the full (capped)
    list only when nothing overlaps at all, so an unanticipated phrasing
    still gets a chance rather than being silently starved to zero attrs.

    fallback_to_full=False (Amendment 17, docs/CPQ_UNIFIED_INTENT_
    CLASSIFIER_PLAN.md): a caller gating whether to make an LLM call at
    all — not just narrowing an already-decided candidate list — needs
    "nothing genuinely overlaps" to mean an empty result, not the full
    list; the default behavior would make that gate fire on every turn.

    Scored by rarity-weighted overlap, not a raw overlap COUNT
    (2026-07-28 fix) — live-verified gap: "change the hardware type"
    against a real 153-filled-attr session scored Hardware Version
    (unique word "hardware") EQUAL to a dozen other "...Type"-suffixed
    attrs (Order Type, Band Class Type, Service Type, etc., all sharing
    the generic word "type") — with 10+ ties and a hard cap of 10, the
    actual match got crowded out before the LLM ever saw it. Each
    matched word now contributes 1/(how many candidates' own vocab
    contains that word) instead of a flat 1 — a word only ONE attr owns
    (like "hardware") scores far higher than one a dozen attrs share
    (like "type"), so a genuinely distinctive match wins over generic
    vocabulary noise regardless of how many attrs happen to share it.
    """
    q_words = set(_WORD_RE.findall(question.lower()))
    if not q_words:
        return candidates[:_LLM_INTENT_RELEVANT_CAP] if fallback_to_full else []
    vocabs = []
    for a in candidates:
        vocab = set(_WORD_RE.findall(a.display_label.lower()))
        for o in a.options:
            vocab |= set(_WORD_RE.findall(o.display_name.lower()))
        vocabs.append(vocab)
    doc_freq: dict[str, int] = {}
    for vocab in vocabs:
        for w in vocab:
            doc_freq[w] = doc_freq.get(w, 0) + 1
    scored = []
    for a, vocab in zip(candidates, vocabs):
        overlap_words = q_words & vocab
        if overlap_words:
            score = sum(1.0 / doc_freq[w] for w in overlap_words)
            scored.append((score, a))
    if not scored:
        return candidates[:_LLM_INTENT_RELEVANT_CAP] if fallback_to_full else []
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [a for _score, a in scored[:_LLM_INTENT_RELEVANT_CAP]]
