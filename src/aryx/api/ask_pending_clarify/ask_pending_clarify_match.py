"""Deterministic-first resolution of a bare reply against the pending-
clarify candidate list, split out of `api/ask_api.py` (Phase 2/11-phase
ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Logic unchanged from the original inline definitions.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_pending_clarify.ask_pending_clarify_llm_classify import (
    _llm_classify_pending_clarify_reply,
)


def _reply_matches_attr_option(reply: str, attr: Any) -> bool:
    """True if `reply` exactly names one of `attr`'s real catalog values.

    docs/config_consistency_issues_2026-07-30.md issue 4 — a bare value
    reply to a "which attribute did you mean?" clarify (e.g. "VHF") often
    isn't unique across candidates (VHF is a legal option on 4 different
    frequency-band-ish attrs in the APX NEXT catalog), so this alone
    can't resolve the ambiguity — it's a building block for the
    anchor-based tie-break below, not a standalone matcher.
    """
    r = (reply or "").strip().lower()
    if not r:
        return False
    for o in (attr.options or []):
        if r == (o.item_value or "").lower() or r == (o.display_name or "").lower():
            return True
    return False


def _match_pending_clarify_reply(
    reply: str,
    candidates: list,
    session: Any,
    workspace_id: int,
) -> tuple[str, str | None]:
    """Resolve a bare reply against the pending-clarify candidate list.

    Returns (status, variable_name) — see
    _llm_classify_pending_clarify_reply's docstring for the 3-way
    contract; the deterministic tiers below only ever return "resolved"
    or defer to that function for "decline"/"unclear".
    """
    r = (reply or "").strip()
    if not r or not candidates:
        return ("unclear", None)
    r_lower = r.lower().strip(" .,:;!?\"'")
    by_vn = {a.variable_name: a for a in candidates}

    # Exact variable_name
    if r in by_vn:
        return ("resolved", r)
    for vn, a in by_vn.items():
        if vn.lower() == r_lower:
            return ("resolved", vn)

    # Exact display label (case-insensitive)
    for a in candidates:
        if (a.display_label or "").lower() == r_lower:
            return ("resolved", a.variable_name)

    # 1-based index
    if r.isdigit():
        idx = int(r) - 1
        if 0 <= idx < len(candidates):
            return ("resolved", candidates[idx].variable_name)

    # Label / vn containment (require uniqueness)
    hits: list[str] = []
    for a in candidates:
        label = (a.display_label or "").lower()
        vn_flat = a.variable_name.lower().replace("_", " ")
        if (
            r_lower in label
            or label in r_lower
            or r_lower in vn_flat
            or vn_flat in r_lower
        ):
            hits.append(a.variable_name)
    if len(hits) == 1:
        return ("resolved", hits[0])

    # Value-based match, anchored on the last clarify this session actually
    # resolved. docs/config_consistency_issues_2026-07-30.md issue 4 —
    # confirmed live: a bare value like "VHF" is a legal option on several
    # of these candidates at once, so an unanchored value match would still
    # be ambiguous; but once the customer already picked one of them
    # earlier (e.g. "Frequency Bands"), a later bare value that's valid for
    # THAT specific attr should resolve to it directly rather than
    # re-asking a question already answered.
    _anchor_vn = session.last_clarified_attr_vn
    if _anchor_vn and _anchor_vn in by_vn and _reply_matches_attr_option(r, by_vn[_anchor_vn]):
        return ("resolved", _anchor_vn)

    # No remembered anchor (or it doesn't apply here) — fall back to a
    # plain value match, only when it's unique across candidates. Never
    # guess when 2+ candidates share the value; that's still genuinely
    # ambiguous and must go to the LLM/re-ask below.
    value_hits = [a.variable_name for a in candidates if _reply_matches_attr_option(r, a)]
    if len(value_hits) == 1:
        return ("resolved", value_hits[0])

    # LLM-first: resolved / explicit decline / unclear.
    return _llm_classify_pending_clarify_reply(r, candidates, session, workspace_id)
