"""LLM detection of a mid-turn topic switch away from the pending
question, and of a decline for a proposed/pending change, split out of
`ask_api.py` (final sweep, Phase 11/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md — docs/CPQ_PENDING_TOPIC_
SWITCH_PLAN_2026_08_11.md / docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_
AUDIT_2026_08_12.md row 15-16). Both are narrow-helper LLM fallbacks
tried only after their respective deterministic check already said no,
short-circuiting the LLM call whenever the deterministic check already
agrees — same cost discipline as every other LLM fallback in this file.
Neither ever invents an answer outside its fixed candidate set. Logic
unchanged from the original inline definitions. `_llm_classify_intent_
core` and `_pending_reply_looks_like_new_request` are read through the
ask_api module object (not imported by name) since tests patch several
ask_api names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_llm_intent_core import _llm_classify_intent_core
from aryx.api.ask_llm_usage_and_new_request_detect import _pending_reply_looks_like_new_request


def _llm_detect_pending_topic_switch(
    question: str, pending_attr: Any, other_attrs: list, workspace_id: int,
) -> str | None:
    """Whether a reply to an actively-pending question is actually the
    customer trying to talk about a DIFFERENT attribute instead — tried
    only when `_pending_reply_looks_like_new_request`'s deterministic
    change-verb/arrow check already said no. Only ever returns an exact
    `other_attrs` variable_name or None — never invents one, never
    guesses when ambiguous.
    """
    candidate_lines = "\n".join(
        f"- {a.variable_name} ({a.display_label})" for a in other_attrs
    )
    sys = (
        "A customer is being asked a single pending question in a product-"
        "configuration chat. Decide whether their reply is actually trying "
        "to answer that pending question, or whether they are instead "
        "trying to talk about a DIFFERENT attribute from the candidate "
        "list — e.g. asking about it, or saying they don't want the "
        "pending one and want the other one instead. Only pick a "
        "variable_name if the message clearly names or clearly refers to "
        "one specific candidate attribute. Never invent a variable_name "
        "that isn't in the candidate list."
    )
    user = (
        f"PENDING QUESTION IS ABOUT: {pending_attr.variable_name} "
        f"({pending_attr.display_label})\n\n"
        "OTHER CANDIDATE ATTRIBUTES (variable_name (label)):\n"
        f"{candidate_lines}\n\n"
        f"USER MESSAGE: {question}\n\n"
        'Reply ONLY as JSON: {"switch_to": "<exact variable_name>" | "none"}'
    )
    valid_targets = {a.variable_name for a in other_attrs}

    def _validate(parsed: dict) -> str | None:
        target = parsed.get("switch_to") or ""
        if target not in valid_targets:
            return None
        return target

    return _llm_classify_intent_core(sys, user, workspace_id, _validate)


def _pending_reply_is_topic_switch(
    question: str, pending_attr: Any, attrs: list, filled: dict,
    filled_multi: dict, workspace_id: int,
) -> bool:
    """Combines the deterministic `_pending_reply_looks_like_new_request`
    check with a narrow LLM fallback for the natural-language redirects
    the regex can't see. Deterministic check runs first and
    short-circuits the LLM call whenever it already agrees.
    """
    if pending_attr is None:
        return False
    if _pending_reply_looks_like_new_request(
        question, pending_attr, attrs, filled, filled_multi,
    ):
        return True
    other_attrs = [a for a in attrs if a.variable_name != pending_attr.variable_name]
    if not other_attrs:
        return False
    switch_vn = _llm_detect_pending_topic_switch(
        question, pending_attr, other_attrs, workspace_id,
    )
    return switch_vn is not None


def _llm_detect_change_decline(
    question: str, attr_label: str, current_value: str, workspace_id: int,
) -> bool:
    """Whether a reply to a proposed/pending change is actually declining
    it (keeping the current value), tried only when the deterministic
    decline regexes already said no. Fails safe to `False` (not a
    decline — try it as a value) on any call/parse failure.
    """
    sys = (
        "A customer was asked whether they want to change a product-"
        "configuration attribute's value, or was in the middle of "
        "changing one. Decide whether their reply explicitly DECLINES "
        "the change (wants to keep the current value, e.g. \"never "
        "mind\", \"forget it\", \"leave it as is\", \"skip that\", "
        "\"on second thought don't bother\") or whether it's a genuine "
        "attempt to state a new value or something else entirely. Only "
        "say yes if the reply clearly rejects making any change at all."
    )
    user = (
        f"ATTRIBUTE: {attr_label}\n"
        f"CURRENT VALUE: {current_value or 'unset'}\n\n"
        f"USER MESSAGE: {question}\n\n"
        'Reply ONLY as JSON: {"declines_change": true | false}'
    )

    def _validate(parsed: dict) -> bool | None:
        val = parsed.get("declines_change")
        if not isinstance(val, bool):
            return None
        return val

    result = _llm_classify_intent_core(sys, user, workspace_id, _validate)
    return bool(result)
