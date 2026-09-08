"""3-way classification of an ambiguous product-switch reply, and the
LLM-first compound change-and-question splitter, split out of
`ask_api.py` (final sweep, Phase 11/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md —
docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md row 21 /
docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §4).
`_llm_classify_switch_reply` is tried only for a genuinely ambiguous
reply — the deterministic checks already catch a clear accept, a clear
decline, or a reply naming a genuinely different real product.
`_llm_split_compound_change_and_question` never invents catalog IDs/
values, only rephrases the customer's own words into two standalone
requests, and returns None (never a wrong split) whenever the message
isn't genuinely compound. Logic unchanged from the original inline
definitions. `_llm_classify_intent_core` is read through the ask_api
module object (not imported by name) since tests patch several ask_api
names by dotted path.
"""

from __future__ import annotations

from aryx.api import ask_api as _ask_api_module


def _llm_classify_switch_reply(
    question: str, candidate_product: str, current_product: str, workspace_id: int,
) -> str:
    """Returns "accept", "decline", or "unclear" — "unclear" (including
    any call/parse failure) must be treated by the caller exactly like
    the existing decline behavior (fail-safe: never completes a switch
    on an ambiguous reply).
    """
    sys = (
        "A customer was asked whether they want to switch their current "
        "product-configuration session to a different product, e.g. "
        "\"Switch to X? (yes/no)\". Classify their reply as exactly one "
        'of: "accept" (they want to switch), "decline" (they want to '
        'stay on the current product), or "unclear" (genuinely '
        "ambiguous, doesn't clearly commit either way — e.g. \"maybe\", "
        "\"I guess\", \"not sure\"). Never guess accept or decline for a "
        "reply that doesn't actually commit."
    )
    user = (
        f"CURRENT PRODUCT: {current_product}\n"
        f"OFFERED SWITCH TO: {candidate_product}\n\n"
        f"USER REPLY: {question}\n\n"
        'Reply ONLY as JSON: {"decision": "accept" | "decline" | "unclear"}'
    )

    def _validate(parsed: dict) -> str | None:
        decision = parsed.get("decision")
        if decision not in ("accept", "decline", "unclear"):
            return None
        return decision

    result = _ask_api_module._llm_classify_intent_core(sys, user, workspace_id, _validate)
    return result if result is not None else "unclear"


def _llm_split_compound_change_and_question(
    question: str, workspace_id: int,
) -> tuple[str, str] | None:
    """Does this message combine a change request AND a separate
    question in one turn? If so, split into two self-contained strings
    so each can be dispatched through its OWN existing pipeline in the
    same turn. Returns None when the message is NOT genuinely compound —
    caller falls through to the existing clarify/ambiguous path
    unchanged, so a wrong split can never happen silently.
    """
    sys = (
        "A customer sent a message to a product configuration assistant. "
        "Determine whether it combines TWO separate things: (1) a request "
        "to CHANGE or SET one attribute's value, and (2) a genuinely "
        "SEPARATE question asking about something else (a current value, "
        "available options, etc.) that is not part of the same change. "
        "If both are clearly present, split the message into two "
        "self-contained requests, each rephrased in the customer's own "
        "words as a complete standalone request. If the message is "
        "really just ONE thing — a single change, a single question, or "
        "multiple changes to different fields with no separate question "
        "mixed in — say it is not compound. Never invent details that "
        "weren't in the original message."
    )
    user = (
        f"MESSAGE: {question}\n\n"
        'Reply ONLY as JSON: {"is_compound": true|false, '
        '"change_text": "<self-contained change request, or empty>", '
        '"question_text": "<self-contained question, or empty>"}'
    )

    def _validate(parsed: dict) -> tuple[str, str] | None:
        if not parsed.get("is_compound"):
            return None
        change_text = (parsed.get("change_text") or "").strip()
        question_text = (parsed.get("question_text") or "").strip()
        if not change_text or not question_text:
            return None
        return (change_text, question_text)

    return _ask_api_module._llm_classify_intent_core(sys, user, workspace_id, _validate)
