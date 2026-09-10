"""LLM-first classification of a reply to a pending scope question, split
out of `api/ask_api.py` (Phase 6/11-phase ask_api decomposition, docs/
RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the
original inline definition.
"""

from __future__ import annotations

from typing import Any, Literal

from aryx.api.ask_llm.ask_llm_intent_core import _llm_classify_intent_core


def _llm_classify_scope_reply(
    reply: str, candidates: list[str], scope_label: str,
    session: Any, workspace_id: int,
) -> tuple[Literal["candidate", "skip", "family_only", "unrelated"], str | None]:
    """LLM-first classification of a reply to a pending scope question
    (product/family/attr-option disambiguation) — docs/CPQ_PRODUCT_
    SCOPE_LLM_FIRST_PLAN_2026_08_13.md.

    Runs BEFORE `resolve_against_scope`'s deterministic ladder, not
    after: classifies the reply's INTENT (does it name one specific
    option, ask to skip/defer this question, name only the broader
    family/category with no specific variant, or neither) — never the
    final value. The LLM's "candidate" guess is only ever a pointer;
    `_resolve_scope_reply` is the only thing allowed to turn it into a
    real answer, by independently confirming it against the actual
    candidate list (never trusted verbatim — same discipline as every
    other `_llm_*` fallback in this file).

    Two live bugs this exists to close:
    - "go further" replied to a pending "Product — choose one" question
      got the same content-free "I didn't get X" re-ask as a garbled
      product name — string-similarity alone has no way to recognize
      "the customer wants to move past this question" as distinct from
      "the customer tried and failed to name a product."
    - "I want quote for APX Next radios" (names the family, no variant)
      got the identical generic "I didn't get X" wording too, reading as
      if the WHOLE message failed to match anything, when really the
      customer is on-topic and just hasn't picked a specific product yet
      — "family_only" gets a response that says so directly instead
      (owner decision: never auto-pick a variant for them, just tell
      them to choose one so the quote can proceed).

    A variant NAMED anywhere in the reply — even embedded in a longer
    sentence ("I want quote for the APX Next All Band radios") — must
    still resolve as "candidate", never "family_only": the presence of
    extra surrounding text is not itself a reason to treat the reply as
    unspecific when it does specify one.
    """
    if not reply.strip() or not candidates:
        return "unrelated", None
    cand_lines = "\n".join(f"- {c}" for c in candidates)
    sys = (
        "You classify a user's reply to a pending multiple-choice "
        f'question about "{scope_label}". Exactly one of four outcomes:\n'
        '- "candidate": the reply clearly and specifically points at ONE '
        'of the listed options (even indirectly, e.g. "the international '
        'one", or embedded in a longer sentence, e.g. "I want quote for '
        'the All Band radios") -- give your best-guess exact string from '
        "the list. A specific variant mentioned ANYWHERE in the reply "
        'always wins, no matter how much other text surrounds it.\n'
        '- "skip": the reply is asking to move past, skip, or defer this '
        'question rather than naming any option (e.g. "go further", '
        '"skip this", "let\'s continue", "come back to this later").\n'
        '- "family_only": the reply is clearly on-topic and about this '
        'same product line, but names only the broader family/category '
        '-- no specific option from the list is identifiable (e.g. "I '
        'want a quote for APX Next radios" when the list is specific '
        "APX NEXT variants).\n"
        '- "unrelated": none of the above -- off-topic or a genuinely '
        "different request.\n"
        'Never guess when unsure -- prefer "unrelated" over a low-'
        'confidence "candidate".'
    )
    user = (
        f"OPTIONS:\n{cand_lines}\n\nUSER REPLY: {reply}\n\n"
        'Reply ONLY as JSON: {"outcome": "candidate"|"skip"|"family_only"'
        '|"unrelated", "guess": "<exact string from OPTIONS, or null>"}'
    )

    def _validate(
        parsed: dict,
    ) -> tuple[Literal["candidate", "skip", "family_only", "unrelated"], str | None]:
        outcome = parsed.get("outcome")
        if outcome not in ("candidate", "skip", "family_only", "unrelated"):
            return "unrelated", None
        if outcome == "candidate":
            guess = parsed.get("guess")
            if not isinstance(guess, str) or guess not in candidates:
                return "unrelated", None
            return "candidate", guess
        return outcome, None

    result = _llm_classify_intent_core(sys, user, workspace_id, _validate, role="answer")
    if result is None:
        # Reject-on-failure (Issues 6/7 discipline): an exception/timeout/
        # malformed reply must never be treated as a confident answer —
        # "unrelated" makes _resolve_scope_reply fall through to the
        # unchanged deterministic ladder, exactly as if this call never
        # happened.
        return "unrelated", None
    return result
