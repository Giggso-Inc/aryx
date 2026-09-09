"""Tier-2 CPQ-intent gate, split out of `api/ask_api.py` (Phase 6/11-
phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-
03.md). Logic unchanged from the original inline definition.
"""

from __future__ import annotations

from aryx.api.ask_llm.ask_llm_intent_core import _llm_classify_intent_core


def _llm_classify_is_cpq_question(
    question: str, workspace_id: int, prior_context: str = "",
) -> bool:
    """Amendment 16 Layer 1 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md):
    Tier-2 intent gate, tried only when `CpqEngine.is_cpq_question`'s
    Tier-1 regex-trigger/ingested-alias check already returned False.
    Never replaces that check, only covers what it structurally can't (a
    genuine request phrased without any trigger word or a recognizable
    product name/alias). Two call sites with structurally different needs:

    1. `run_ask`'s fresh-turn router — deciding whether to enter CPQ mode
       at all, before any CPQ session/context exists. No `prior_context`
       is passed here; this classification is, and must stay, the raw
       sentence alone.
    2. `_synthesise`'s mid-session Q&A scope check — deciding whether an
       in-flight follow-up question is still in scope. Live-confirmed gap
       (docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §14): "what
       is the error" right after the CPQ engine's own gate error was
       wrongly refused as out-of-scope, because classified alone it reads
       as an unrelated tech-support question — the one fact that would
       make it recognizably relevant (the prior turn WAS an error) was
       never shown to the classifier. `prior_context` (the recent
       conversation, already computed by the caller) fixes this for call
       site 2 without changing call site 1's behavior at all.

    Deliberately biased toward "quote" on anything but a confident "no":
    live-confirmed twice this session (a missing regex plural, an
    alias-fallback that only checked internal BOM codes) that a false
    "no" here means a genuine CPQ request silently exits to the generic
    LLM pipeline with no error — bypassing this engine's entire
    "never guess" discipline. A false "yes" costs only Step 1's own
    anchor-prompting asking a clarifying question, the same as any
    ordinary first turn. An LLM-call failure (exception, malformed JSON)
    is NOT covered by that bias — it returns False, the same default this
    turn already had before this gate existed, since a failed call
    provides no information at all, positive or negative.
    """
    sys = (
        "You classify whether a customer's message is asking to "
        "configure, quote, or order a product — a CPQ/configuration "
        "request — versus a general question or something unrelated. "
        "Bias toward \"quote\" whenever the message plausibly could be "
        "about ordering or configuring something, even if phrased "
        "unusually or missing an obvious trigger word; only classify as "
        "\"not_quote\" when you are confident it is NOT that at all. "
        "If RECENT CONTEXT is given, judge the message as a likely "
        "follow-up to it — e.g. a question asking to explain, clarify, "
        "or elaborate on something the assistant just said (including an "
        "error or gate message from THIS product-configuration system) "
        "counts as \"quote\", even if the bare message alone would look "
        "like an unrelated general question."
    )
    context_block = (
        f"\nRECENT CONVERSATION (for context only — classify the MESSAGE "
        f"below, but consider whether it plausibly follows up on this):\n"
        f"{prior_context}\n"
        if prior_context.strip() else ""
    )
    user = (
        f"{context_block}MESSAGE: {question}\n\n"
        'Reply ONLY as JSON: {"classification": "quote"|"not_quote"}'
    )

    def _validate(parsed: dict) -> bool | None:
        classification = parsed.get("classification")
        if classification not in ("quote", "not_quote"):
            return None
        return classification == "quote"

    return _llm_classify_intent_core(sys, user, workspace_id, _validate) is True
