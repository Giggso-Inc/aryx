"""Building catalog-grounded candidate lists for a pending-clarify prompt,
split out of `api/ask_api.py` (Phase 2/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the
original inline definition; the catalog-wide-naming-parts helper and the
per-attribute scoring loop live in the sibling `ask_pending_clarify_
constants.py`/`ask_pending_clarify_scoring.py` purely to keep this file
under the line cap.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_pending_clarify.ask_pending_clarify_constants import (
    _CLARIFY_STOPWORDS,
    _WORD_TOKEN_RE,
    _catalog_wide_naming_parts,
)
from aryx.api.ask_pending_clarify.ask_pending_clarify_scoring import _score_clarify_candidates


def _ground_clarify_candidates(
    question: str,
    attrs: list,
    session: Any,
    clarifying_question: str | None = None,
    hidden_vns: set[str] | None = None,
) -> list:
    """Build candidate attrs from REAL catalog labels only.

    Prefer filled attrs with word-overlap against the vague utterance;
    also accept labels that appear (validated) inside the LLM clarify text
    so examples like "Hardware Version" are kept only when they exist in
    the catalog — never free-invented names.

    hidden_vns — docs/config_consistency_issues_2026-07-30.md issue 1:
    live-confirmed bug — a change request ("add VHF... as frequency
    bands") landed on modelSelectionFrequencyBandMsl_astro, an attribute
    the catalog's own hiding rule gates OFF for Single-Band products,
    because it remained a valid word-overlap candidate right alongside
    the correct, visible modelSelectionFrequencyBands_astro in this same
    disambiguation list. An attribute currently hidden for this product
    must never be offered as something to change at all, regardless of
    how well its label/name happens to score.
    """
    _catalog_wide_parts = _catalog_wide_naming_parts(attrs)
    q_words = {
        w for w in _WORD_TOKEN_RE.findall((question or "").lower())
        if w not in _CLARIFY_STOPWORDS and w not in _catalog_wide_parts and len(w) >= 2
    }
    q_lower = (question or "").lower()
    cq_lower = (clarifying_question or "").lower()
    _hidden = hidden_vns or set()

    by_vn, scores, strong_vns = _score_clarify_candidates(
        attrs, session, q_words, q_lower, cq_lower, _hidden,
    )

    # Highest relevance score first; label length only breaks ties among
    # equally-relevant candidates.
    candidates = list(by_vn.values())
    candidates.sort(
        key=lambda a: (
            -scores.get(a.variable_name, 0),
            -len(a.display_label or ""),
            a.display_label or "",
            a.variable_name,
        ),
    )

    # When exactly one candidate carries any strong, explicit grounding
    # (its own label/variable_name verbatim in the message or the
    # clarifying question) and every other admitted candidate is here
    # only via incidental word-overlap, the ambiguity is resolved
    # outright — the customer didn't leave anything for the model to
    # guess. Two or more strongly-grounded candidates (e.g. the LLM's own
    # clarifying question naming both "Frequency Bands" and "Additional
    # Frequency Bands") is a real multi-target disambiguation, and the
    # full candidate pool is kept exactly as before.
    if len(strong_vns) == 1:
        return [a for a in candidates if a.variable_name in strong_vns]

    return candidates[:8]
