"""Pending-scope re-ask phrasing and structured logging.

Split out of `cpq/pending_scope.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def format_did_you_mean(
    reply: str,
    suggestions: list[str],
    *,
    numbered: bool = False,
    scope_label: str = "",
    confident_single: bool = False,
) -> str:
    """Scoped re-ask — never mentions the full catalog.

    confident_single — only meaningful when exactly one suggestion is
    passed. True keeps the "did you mean **X**?" phrasing (a genuine
    near-miss: a real substring hit, or a fuzzy score close to the accept
    threshold). False renders the same single suggestion as a plain
    numbered pick instead — confirmed live (2026-08-08): resending an
    entire unrelated sentence as a reply scored just over the bare
    fuzzy-suggest floor against one real option purely by coincidental
    character overlap, and phrasing that as a confident guess overstated
    the actual match quality. The caller (_scoped_reask_response) decides
    this from the underlying ScopeResolve.score/tier, not this function.

    Live-confirmed wording bug (2026-08-13): quoting the reply verbatim
    ("I didn't get **{reply}**...") reads fine for a short, typo'd
    product-name attempt, but produces garbled, confusing phrasing for a
    full sentence -- "I didn't get **I wanted to set the product** for
    Product" sounds like a broken double-negative, not a clarification
    request. A short reply (<=5 words) is still quoted, since that's the
    genuinely useful case (showing the customer exactly what didn't
    match); a longer one is replaced with generic "that reply" wording.
    """
    reply_stripped = (reply or "").strip()
    reply_s = (
        reply_stripped if reply_stripped and len(reply_stripped.split()) <= 5
        else "that reply"
    )
    label_bit = f" for **{scope_label}**" if scope_label else ""
    if numbered or len(suggestions) > 3:
        lines = "\n".join(f"{i + 1}. **{s}**" for i, s in enumerate(suggestions))
        return (
            f"I didn't get **{reply_s}**{label_bit}. "
            f"Please pick one of these (same list as before):\n\n{lines}"
        )
    if not suggestions:
        return (
            f"I didn't get **{reply_s}**{label_bit}. "
            f"Please reply with one of the options I listed."
        )
    if len(suggestions) == 1:
        if confident_single:
            return (
                f"I didn't get **{reply_s}**{label_bit} — did you mean "
                f"**{suggestions[0]}**? Reply with the name, or something "
                f"else from the same list."
            )
        return (
            f"I didn't get **{reply_s}**{label_bit} as a match. "
            f"Please pick one of these (same list as before):\n\n"
            f"1. **{suggestions[0]}**"
        )
    sug = ", ".join(f"**{s}**" for s in suggestions)
    return (
        f"I didn't get **{reply_s}**{label_bit} — did you mean {sug}, "
        f"or something else from the same list?"
    )


def log_scope_retained(
    *,
    run_id: str,
    reply: str,
    kind: str,
    n_candidates: int,
    suggestions: list[str],
    misses: int,
) -> None:
    logger.info(
        "cpq_scope_retained run_id=%s kind=%s n=%d misses=%d reply=%r "
        "suggestions=%r",
        run_id or "-", kind, n_candidates, misses, (reply or "")[:80],
        suggestions[:5],
    )


def log_scope_lost(
    *,
    run_id: str,
    reply: str,
    reason: str,
) -> None:
    """Should be structurally impossible after PROMPT 7 — alert if seen."""
    logger.error(
        "cpq_scope_lost run_id=%s reason=%s reply=%r",
        run_id or "-", reason, (reply or "")[:120],
    )
