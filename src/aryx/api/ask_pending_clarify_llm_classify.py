"""LLM-first 3-way classification of a pending-clarify reply, split out of
`api/ask_api.py` (Phase 2/11-phase ask_api decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original inline
definition. `_llm_classify_intent_core` and `logger` are read through the
ask_api MODULE object (not imported by name) since ask_api tests patch
several of its own module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_llm_intent_core import _llm_classify_intent_core


def _llm_classify_pending_clarify_reply(
    reply: str, candidates: list, session: Any, workspace_id: int,
) -> tuple[str, str | None]:
    """LLM-first classification of a pending-clarify reply into exactly
    one of three outcomes, replacing regex-based decline detection
    (docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §5.2 — a
    keyword regex missed real phrasing like "don't WANTED to select"
    during testing; an LLM classification doesn't have that brittleness).

    Only reached after the cheap deterministic tiers in
    _match_pending_clarify_reply (exact variable_name, exact label,
    1-based index, containment) already found nothing — same
    "deterministic first, LLM only for genuinely looser phrasing"
    discipline as _llm_resolve_label_collision, which this scopes
    alongside rather than replaces (that function's other 5 call sites
    are untouched — this is a separate function for this one call site
    only, since its 3-way contract differs from that function's plain
    resolve-or-nothing one).

    Returns (status, variable_name):
      - ("resolved", vn)  — reply clearly names or picks one candidate
      - ("decline", None) — reply explicitly rejects all candidates
      - ("unclear", None) — reply doesn't address the question at all
    """
    from aryx.api import ask_api as _ask_api_module
    catalog_lines = [
        f"- {a.variable_name} [{a.select_type}] ({a.display_label}): "
        f"current={session.filled_multi.get(a.variable_name) or session.display_filled.get(a.variable_name)!r}"
        for a in candidates
    ]
    sys = (
        "A customer was asked to pick which of several candidate "
        "attributes they meant, from a numbered list. Classify their "
        "reply as exactly one of: "
        '"resolved" (clearly names or picks one candidate), '
        '"decline" (explicitly rejects all of them — e.g. "no", "none of '
        "these\", \"that's not what I meant\", even with loose/incorrect "
        'grammar), or "unclear" (doesn\'t address the question at all — '
        "a totally unrelated new request). Only use variable_names from "
        "the list given — never invent one."
    )
    user = (
        "CANDIDATES (variable_name [select_type] (label): current=...):\n"
        + "\n".join(catalog_lines)
        + f"\n\nUSER REPLY: {reply}\n\n"
        'Reply ONLY as JSON: {"status": "resolved"|"decline"|"unclear", '
        '"variable_name": "<exact name from list, or empty>"}'
    )
    valid_vns = {a.variable_name for a in candidates}

    def _validate(parsed: dict) -> tuple[str, str | None] | None:
        status = parsed.get("status")
        if status not in ("resolved", "decline", "unclear"):
            return None
        if status == "resolved":
            vn = parsed.get("variable_name") or ""
            if vn not in valid_vns:
                _ask_api_module.logger.debug(
                    "llm pending-clarify classify: model named vn %r not "
                    "in candidates %r", vn, valid_vns,
                )
                return ("unclear", None)
            return ("resolved", vn)
        return (status, None)

    result = _llm_classify_intent_core(
        sys, user, workspace_id, _validate,
    )
    return result if result is not None else ("unclear", None)
