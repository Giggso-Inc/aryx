"""Scope gate for the general Ask synthesis path, split out of `api/
ask_api.py` (Phase 6/11-phase ask_api decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original inline
definition.
"""

from __future__ import annotations

from aryx.api.ask_llm_intent_core import _llm_classify_intent_core


def _llm_classify_is_ask_in_scope(
    question: str, workspace_id: int, prior_context: str = "",
) -> bool:
    """Scope gate for the general Ask synthesis path (`_synthesise`'s
    call site only — NOT the CPQ-routing call site in `run_ask`, which
    must keep using `_llm_classify_is_cpq_question`'s narrower,
    quote-biased judgment).

    `_llm_classify_is_cpq_question` was previously reused here, but that
    function only ever answers "is this an order/configure/quote
    request?" — confirmed live this caused the Ask feature to refuse
    almost every question, including legitimate lookups against tracked
    data (e.g. "what are the entities present in suppliers?"), because
    most real questions aren't literally quote/order requests and so
    correctly got `not_quote` from that classifier, which this call site
    then wrongly treated as "off-topic."

    This classifier answers the broader, actually-relevant question for
    Ask: is this about product configuration/quoting OR the enterprise/
    catalog data this system tracks at all? Only a question genuinely
    unrelated to that domain (small talk, an unrelated topic) should
    classify as out of scope.

    `prior_context` (docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md
    §14, ported from `_llm_classify_is_cpq_question` onto this broader
    classifier since this — not that one — is the call site that gates
    general Ask): the recent conversation, when the caller has it, so a
    mid-session follow-up like "what is the error" can be recognized as
    in-scope when the prior turn was the engine's own gate error, rather
    than classified alone as an unrelated tech-support question.

    Fails OPEN, not closed: `_llm_classify_intent_core` returns `None` on
    a malformed reply or an LLM-call exception, same as every other
    caller of that shared skeleton. Collapsing that `None` into `False`
    (as an earlier version of this function did via `is True`) recreates
    the exact bug this function exists to fix — a classification
    failure would silently withhold valid graph facts and reproduce the
    blanket "outside what I track" refusal, indistinguishable from a
    genuine out-of-scope question. Only an explicit `out_of_scope`
    result should count as out of scope; a failed or unparseable call
    provides no information at all and must not be treated as evidence
    either way, so it's treated as in-scope.
    """
    sys = (
        "You classify whether a customer's message is in scope for a "
        "product-configuration and enterprise-data assistant — meaning "
        "it asks about product configuration, quoting/ordering, OR the "
        "catalog/enterprise data this system tracks (entities, "
        "attributes, relationships, records) in any way. "
        "Bias toward \"in_scope\" whenever the message plausibly could be "
        "asking about tracked data or product configuration, even if "
        "phrased as a general question rather than a quote request; only "
        "classify as \"out_of_scope\" when you are confident it is about "
        "something else entirely (e.g. small talk, an unrelated topic)."
    )
    context_block = (
        f"\nRECENT CONVERSATION (for context only — classify the MESSAGE "
        f"below, but consider whether it plausibly follows up on this):\n"
        f"{prior_context}\n"
        if prior_context.strip() else ""
    )
    user = (
        f"{context_block}MESSAGE: {question}\n\n"
        'Reply ONLY as JSON: {"classification": "in_scope"|"out_of_scope"}'
    )

    def _validate(parsed: dict) -> bool | None:
        classification = parsed.get("classification")
        if classification not in ("in_scope", "out_of_scope"):
            return None
        return classification == "in_scope"

    result = _llm_classify_intent_core(sys, user, workspace_id, _validate)
    return result is not False
