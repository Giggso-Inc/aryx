""""Did you mean one of these?" product candidates (Phase 4 step 11
extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

`suggest_product_candidates` is the lower-confidence sibling of
`detect_product_mention`: the same alias inventory and the same
`_fuzzy_score_candidates` scoring, but the "maybe, not confident" band
between the suggest and match thresholds, so an attempted product
mention is never silently ignored.

Both thresholds are read off the engine MODULE object; the alias map and
both scoring helpers go back through the passed-in `engine` instance so
their patches still apply.
"""

from __future__ import annotations

import re
from typing import Any

from aryx.cpq import engine as _engine_module


def suggest_product_candidates(
    engine: Any, question: str, reader: Any, workspace_id: int,
    exclude: str = "", limit: int = 5,
    alias_map: dict[str, str] | None = None,
) -> list[str]:
    """Up to `limit` real ingested product names whose fuzzy similarity
    to `question` falls in the "maybe, not confident" band — at or
    above _PRODUCT_FUZZY_SUGGEST_THRESHOLD but below
    detect_product_mention's own confirm-worthy _PRODUCT_FUZZY_MATCH_THRESHOLD.

    Used when a mid-conversation message seems to be attempting to
    name a product but doesn't clearly match anything — instead of
    silently ignoring it (today's behavior when detect_product_mention
    returns ""), the caller can offer these as "did you mean one of
    these?" candidates rather than leaving the customer's real intent
    unrecognised with no signal anything was ambiguous.

    Returns [] when nothing scores in that band — either
    detect_product_mention already found a confident match, or the
    message truly has no product-name signal at all (the common case
    for an ordinary configuration answer).

    Scores the same alias inventory detect_product_mention matches
    against (family names + catalog-tree names), then maps each
    in-band alias back to its owning FAMILY name — suggestions are
    always family names, because that's the value a confirmed switch
    anchors the session to. Aliases whose family is `exclude` (the
    session's current product) are skipped; duplicate families from
    multiple in-band aliases are collapsed keeping best-score order.

    alias_map — pre-fetched ingested_product_alias_map result; see
    detect_product_mention. This method runs on EVERY ordinary answer
    turn (the no-match path), so re-fetching here doubled the
    graph+RDB round-trips per turn (review finding P2). When None,
    self-fetches as before.
    """
    q_norm = re.sub(r"[^a-z0-9]", "", question.lower())
    if not q_norm:
        return []
    if alias_map is None:
        if reader is None:
            return []
        alias_map = engine.ingested_product_alias_map(reader, workspace_id)
    exclude_norm = exclude.strip().lower()
    ordered = [
        (name, re.sub(r"[^a-z0-9]", "", name.lower()))
        for name, family in alias_map.items()
        if family.strip().lower() != exclude_norm
    ]
    scored = engine._fuzzy_score_candidates(
        q_norm, ordered, question_tokens=engine._question_tokens(question),
    )
    suggestions: list[str] = []
    for name, score in scored:
        if not (
            _engine_module._PRODUCT_FUZZY_SUGGEST_THRESHOLD
            <= score
            < _engine_module._PRODUCT_FUZZY_MATCH_THRESHOLD
        ):
            continue
        family = alias_map[name]
        if family not in suggestions:
            suggestions.append(family)
        if len(suggestions) >= limit:
            break
    return suggestions
