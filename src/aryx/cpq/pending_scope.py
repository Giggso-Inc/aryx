"""Durable option / product candidate scope for CPQ reply matching.

PROMPT 7 — when the engine shows a candidate list (family disambiguation,
constrained product options, attr options, "did you mean" suggestions),
the next reply must be resolved against THAT list first. Losing scope is
the same family of bug as gateway clarify-amnesia.

Scope is stored flat on CpqSession (pending_scope_*) for session_data echo.
This module stays free of FastAPI / graph imports so offline regression
can load it.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Literal

logger = logging.getLogger(__name__)

ScopeKind = Literal[
    "family_disambiguation",
    "product_options",
    "attr_options",
    "product_suggestions",
    "",
]

# Fuzzy accept threshold for in-scope recovery (slightly looser than
# product-mention confirm 0.82 — short typo replies need room).
_SCOPE_FUZZY_ACCEPT = 0.72
_SCOPE_FUZZY_SUGGEST = 0.55
_SCOPE_FUZZY_TOP_N = 3
_SCOPE_MISS_LOOP_EXIT = 2

_SCOPE_KINDS = frozenset({
    "family_disambiguation",
    "product_options",
    "attr_options",
    "product_suggestions",
})


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _score(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


@dataclass(frozen=True)
class ScopeResolve:
    """Result of resolving a reply against pending_scope.candidates."""

    matched: str | None
    suggestions: list[str]
    tier: str  # exact | partial | fuzzy | miss | empty


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
    """Build display/item strings for scope from MenuOption-like objects."""
    allowed = set(constrained_item_values) if constrained_item_values is not None else None
    out: list[str] = []
    for o in options or []:
        iv = getattr(o, "item_value", "") or ""
        dn = getattr(o, "display_name", "") or iv
        if allowed is not None and iv not in allowed:
            continue
        # Prefer display for "did you mean"; keep item_value if distinct
        if dn.strip():
            out.append(dn.strip())
        if iv.strip() and iv.strip().lower() != (dn or "").strip().lower():
            out.append(iv.strip())
    return out


def resolve_against_scope(
    reply: str,
    candidates: list[str],
    *,
    fuzzy_accept: float = _SCOPE_FUZZY_ACCEPT,
    fuzzy_suggest: float = _SCOPE_FUZZY_SUGGEST,
    top_n: int = _SCOPE_FUZZY_TOP_N,
) -> ScopeResolve:
    """Ladder: exact → partial/substring → fuzzy → miss (+ suggestions).

    Partial-word preserves live "Federal" → "… (Federal)" behavior.
    Fuzzy recovers pet names / typos ("r7ex", "Asr") *within* candidates.
    """
    r = (reply or "").strip()
    if not candidates:
        return ScopeResolve(None, [], "empty")
    if not r:
        return ScopeResolve(None, list(candidates[:top_n]), "miss")

    r_lower = r.lower().strip(" .,:;!?\"'")
    r_norm = _norm(r)

    # (i) Exact — full string or digit index
    if r.isdigit():
        idx = int(r) - 1
        if 0 <= idx < len(candidates):
            return ScopeResolve(candidates[idx], [], "exact")
    for c in candidates:
        if c.lower().strip() == r_lower:
            return ScopeResolve(c, [], "exact")
        if _norm(c) == r_norm and r_norm:
            return ScopeResolve(c, [], "exact")

    # (ii) Partial / substring (Federal-in-scope)
    partial_hits: list[str] = []
    for c in candidates:
        c_lower = c.lower()
        c_norm = _norm(c)
        if len(r_lower) >= 2 and (
            r_lower in c_lower
            or (len(c_lower) >= 2 and c_lower in r_lower)
            or (r_norm and len(r_norm) >= 2 and r_norm in c_norm)
            or (c_norm and len(c_norm) >= 2 and c_norm in r_norm)
        ):
            # Word-ish: avoid tiny 1-char noise
            partial_hits.append(c)
    if len(partial_hits) == 1:
        return ScopeResolve(partial_hits[0], [], "partial")
    if len(partial_hits) > 1:
        # Prefer longest candidate (more specific) when multiple contain reply
        best = max(partial_hits, key=lambda s: len(_norm(s)))
        # If several share same length specificity, still ambiguous → suggest
        tops = sorted(partial_hits, key=lambda s: len(_norm(s)), reverse=True)
        if len(_norm(tops[0])) > len(_norm(tops[1])) if len(tops) > 1 else True:
            # unique longest wins for partial
            longest = tops[0]
            if sum(1 for t in tops if len(_norm(t)) == len(_norm(longest))) == 1:
                return ScopeResolve(longest, [], "partial")
        return ScopeResolve(None, tops[:top_n], "miss")

    # (iii) Fuzzy edit-distance / ratio against each candidate
    scored: list[tuple[str, float]] = []
    for c in candidates:
        c_norm = _norm(c)
        if not c_norm:
            continue
        # Bidirectional ratio + prefix bonus for short replies
        s = max(_score(r_norm, c_norm), _score(r_lower, c.lower()))
        if r_norm and c_norm.startswith(r_norm):
            s = max(s, 0.85)
        if r_norm and r_norm in c_norm and len(r_norm) >= 3:
            s = max(s, 0.80)
        # Sliding short window over long names
        if len(r_norm) >= 3 and len(c_norm) > len(r_norm):
            window = len(r_norm)
            for i in range(0, len(c_norm) - window + 1):
                s = max(s, _score(r_norm, c_norm[i:i + window]))
        scored.append((c, s))
    scored.sort(key=lambda t: t[1], reverse=True)
    if scored and scored[0][1] >= fuzzy_accept:
        # Unique clear winner
        if len(scored) == 1 or scored[0][1] - scored[1][1] >= 0.05:
            return ScopeResolve(scored[0][0], [], "fuzzy")
        # Near-ties → suggestions
        top = [c for c, sc in scored if sc >= fuzzy_suggest][:top_n]
        return ScopeResolve(None, top or [scored[0][0]], "miss")

    suggestions = [c for c, sc in scored if sc >= fuzzy_suggest][:top_n]
    if not suggestions and scored:
        suggestions = [scored[0][0]]
    return ScopeResolve(None, suggestions, "miss")


def format_did_you_mean(
    reply: str,
    suggestions: list[str],
    *,
    numbered: bool = False,
    scope_label: str = "",
) -> str:
    """Scoped re-ask — never mentions the full catalog."""
    reply_s = (reply or "").strip() or "that"
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
        return (
            f"I didn't get **{reply_s}**{label_bit} — did you mean "
            f"**{suggestions[0]}**? Reply with the name, or something else "
            f"from the same list."
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


def scope_loop_exit_threshold() -> int:
    return _SCOPE_MISS_LOOP_EXIT
