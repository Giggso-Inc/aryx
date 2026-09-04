"""Pending-scope state on CpqSession: set/clear + building candidate lists.

Split out of `cpq/pending_scope.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)

ScopeKind = Literal[
    "family_disambiguation",
    "product_options",
    "attr_options",
    "product_suggestions",
    "",
]

_SCOPE_KINDS = frozenset({
    "family_disambiguation",
    "product_options",
    "attr_options",
    "product_suggestions",
})


def clear_pending_scope(session: Any) -> None:
    """Clear all pending_scope_* fields on a CpqSession-like object."""
    session.pending_scope_kind = ""
    session.pending_scope_candidates = []
    session.pending_scope_origin_question = ""
    session.pending_scope_asked_turn = 0
    session.pending_scope_misses = 0
    session.pending_scope_attr_vn = ""


def set_pending_scope(
    session: Any,
    *,
    kind: str,
    candidates: list[str],
    origin_question: str = "",
    attr_vn: str = "",
    asked_turn: int | None = None,
) -> None:
    """Remember the list we just showed the user.

    Dedupes candidates (order-preserving). No-op when candidates empty
    (never store an empty "scope" that would block real matching).
    """
    clean: list[str] = []
    seen: set[str] = set()
    for c in candidates or []:
        s = (c or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        clean.append(s)
    if not clean:
        return
    kind_s = kind if kind in _SCOPE_KINDS else "attr_options"
    session.pending_scope_kind = kind_s
    session.pending_scope_candidates = clean
    session.pending_scope_origin_question = (origin_question or "")[:500]
    session.pending_scope_asked_turn = (
        int(asked_turn) if asked_turn is not None
        else int(getattr(session, "turn", 0) or 0)
    )
    session.pending_scope_misses = 0
    session.pending_scope_attr_vn = (attr_vn or "").strip()
    logger.info(
        "cpq_scope_set kind=%s n=%d attr=%r turn=%s",
        kind_s, len(clean), session.pending_scope_attr_vn,
        session.pending_scope_asked_turn,
    )


def candidates_from_attr_options(
    options: list[Any],
    constrained_item_values: list[str] | None = None,
) -> list[str]:
    """Build display-name strings for scope from MenuOption-like objects.

    Display name ONLY, never the raw internal item_value (2026-08-13
    live-confirmed bug): this list is both what a reply is matched
    against AND what gets echoed back verbatim to the customer in a
    numbered re-ask (`_scoped_reask_response`'s "same list as before"
    fallback) whenever it collapses to the full candidate set.
    Previously also appending item_value whenever it differed from
    display_name (e.g. item_value "APX NEXT MULTI" for the real
    "APX NEXT All Band" option) meant internal catalog codes -- never
    meant to be customer-facing -- leaked into that visible re-ask as
    if they were separate, legitimate product choices, inflating a
    real 7-option list into an 11-entry one. `resolve_against_scope`'s
    own partial/fuzzy tiers already recover a customer typing an
    internal-code-shaped reply against the display name alone, so
    matching flexibility isn't lost by dropping item_value here.
    """
    allowed = set(constrained_item_values) if constrained_item_values is not None else None
    out: list[str] = []
    for o in options or []:
        iv = getattr(o, "item_value", "") or ""
        dn = getattr(o, "display_name", "") or iv
        if allowed is not None and iv not in allowed:
            continue
        if dn.strip():
            out.append(dn.strip())
    return out
