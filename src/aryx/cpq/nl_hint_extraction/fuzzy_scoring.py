"""Deterministic fuzzy scoring of product-name candidates (Phase 4 step
11 extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

The shared, no-LLM scoring both `detect_product_mention` (confirm-worthy
band) and `suggest_product_candidates` ("maybe" band) run over -- one
implementation, two thresholds, so the two can never disagree about how
similar a mention is. `_question_tokens` supplies the word-level
abbreviation-prefix signal layered on top of the sliding window.

Neither function needs the engine instance (both were @staticmethod), so
neither takes an `engine` parameter. `string_score` and the thresholds
are read off the engine MODULE object so the original bare-global
references -- and any patch of them -- resolve at call time as before.
"""

from __future__ import annotations

import re

from aryx.cpq import engine as _engine_module


def _question_tokens(question: str) -> frozenset[str]:
    """Individual normalized word tokens from `question`, filtered to
    those long enough to carry brand-abbreviation signal (see
    `_ABBR_PREFIX_MIN_LEN`). Distinct from q_norm, which glues the
    whole question into one string for substring/sliding-window
    checks — this stays word-separated so a short mention ("APX")
    isn't diluted by neighboring filler ("quote", "qty", "10").
    """
    return frozenset(
        t for t in re.findall(r"[a-z0-9]+", (question or "").lower())
        if len(t) >= _engine_module._ABBR_PREFIX_MIN_LEN
    )


def _fuzzy_score_candidates(
    q_norm: str, ordered: list[tuple[str, str]],
    question_tokens: frozenset[str] | None = None,
) -> list[tuple[str, float]]:
    """Best deterministic fuzzy score of each (name, name_norm) pair
    against q_norm — a sliding window the length of the candidate's
    normalized name, scored via aryx.resolution.classical.string_score.
    Shared by detect_product_mention's confirm-worthy match and
    suggest_product_candidates' lower "maybe" band, so both use the
    exact same scoring, just different thresholds. Sorted descending;
    names shorter than _HINT_MIN_PHRASE_LEN are never scored (same
    guard used elsewhere to stop short names from spuriously matching
    unrelated text).

    `question_tokens` (see `_question_tokens`) adds a second, word-level
    signal on top of the whole-string sliding window: any token that is
    a genuine prefix of a candidate's normalized name bumps that
    candidate's score into the "suggest" band via `_ABBR_PREFIX_SCORE`,
    even when the whole-sentence window carries no useful signal for a
    short/vague mention. Purely additive (`max`) — never lowers a score
    the sliding window already found on its own.
    """
    scored: list[tuple[str, float]] = []
    for name, name_norm in ordered:
        if len(name_norm) < _engine_module._HINT_MIN_PHRASE_LEN:
            continue
        window = len(name_norm)
        span = max(1, len(q_norm) - window + 1)
        best = 0.0
        for i in range(span):
            best = max(
                best,
                _engine_module.string_score(name_norm, q_norm[i:i + window]),
            )
        if question_tokens and any(
            name_norm.startswith(tok) for tok in question_tokens
        ):
            best = max(best, _engine_module._ABBR_PREFIX_SCORE)
        scored.append((name, best))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored
