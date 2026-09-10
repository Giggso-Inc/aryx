"""Pending-scope reply resolution: exact/partial/fuzzy matching ladder.

Split out of `cpq/pending_scope.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Kept as one cohesive module rather than split further —
`resolve_against_scope`'s three tiers share the same normalization helpers
and its thresholds are cross-referenced by live-incident docstrings that
would fragment across files for no real benefit. Zero test patches against
this module — confirmed via grep.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

# Fuzzy accept threshold for in-scope recovery (slightly looser than
# product-mention confirm 0.82 — short typo replies need room).
_SCOPE_FUZZY_ACCEPT = 0.72
_SCOPE_FUZZY_SUGGEST = 0.55
_SCOPE_FUZZY_TOP_N = 3
_SCOPE_MISS_LOOP_EXIT = 2

# Below this, a single "miss"-tier suggestion is coincidental character
# overlap, not a real near-miss -- confirmed live (2026-08-08): resending
# an entire unrelated sentence ("Give me quote of APXNEXT with 10 qty for
# US") as the reply to a pending Product question scored just over
# _SCOPE_FUZZY_SUGGEST (0.55) against "APX NEXT (International)" purely
# because both strings happen to share "APX NEXT" — nowhere near a genuine
# typo/abbreviation match. Framing that as a confident "did you mean X?"
# misrepresents the actual signal. Sits above the bare suggest floor but
# below the real accept threshold, the same "wide middle band is noise"
# shape as _PRODUCT_FUZZY_SUGGEST_THRESHOLD in engine.py.
_DID_YOU_MEAN_CONFIDENT_FLOOR = 0.65


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
    # Top candidate's match strength when tier == "miss" (0.0 otherwise /
    # not meaningful for exact|partial|fuzzy, which already resolved).
    # Lets a caller distinguish a near-miss suggestion from coincidental
    # character overlap on a long, unrelated reply.
    score: float = 0.0


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
        # Ambiguous, but every one of these is a genuine substring hit
        # (not coincidental fuzzy overlap) -- score=1.0 keeps "did you
        # mean" phrasing meaningful when this collapses to a single item.
        return ScopeResolve(None, tops[:top_n], "miss", 1.0)

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
        # Near-ties → suggestions (top score already cleared fuzzy_accept)
        top = [c for c, sc in scored if sc >= fuzzy_suggest][:top_n]
        return ScopeResolve(None, top or [scored[0][0]], "miss", scored[0][1])

    suggestions = [c for c, sc in scored if sc >= fuzzy_suggest][:top_n]
    if not suggestions and scored:
        suggestions = [scored[0][0]]
    return ScopeResolve(None, suggestions, "miss", scored[0][1] if scored else 0.0)


def scope_loop_exit_threshold() -> int:
    return _SCOPE_MISS_LOOP_EXIT


def is_confident_scope_suggestion(res: ScopeResolve) -> bool:
    """True when a single "miss"-tier suggestion is a genuine near-miss
    (real substring hit, or a fuzzy score near the accept threshold) --
    False when it only cleared the bare suggestion floor, the shape a long,
    unrelated reply's coincidental character overlap produces."""
    return res.tier == "miss" and res.score >= _DID_YOU_MEAN_CONFIDENT_FLOOR
