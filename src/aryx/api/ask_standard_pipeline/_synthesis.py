"""Answer synthesis for the standard (non-CPQ) Ask pipeline.

Split out of `ask_api.py` per
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md Phase 4 step 1.

`_llm_classify_is_ask_in_scope`'s true home is
`ask_llm_classify_is_ask_in_scope.py` (docs/RAVEN_STYLE_COMPLIANCE_PLAN_
2026-09-03.md's ask_api.py external-import-site rewrite) -- imported
directly, since no test patches it by dotted path.
"""
from __future__ import annotations

import logging
import time

from aryx.llm import llm_runtime
from aryx.api.ask_llm.ask_llm_classify_is_ask_in_scope import _llm_classify_is_ask_in_scope
from aryx.api.ask_request_models import Turn
from aryx.api.ask_standard_pipeline._rewrite import _MAX_ANSWER_LINES, _enforce_plain_answer
from aryx.api.ask_standard_pipeline._text_utils import _recent, _strip_think

logger = logging.getLogger(__name__)


def _synthesise(question: str, context: str, overview: str = "",
                history: list[Turn] | None = None,
                workspace_id: int = 1, session_values: str = "") -> tuple[str, int, int, int]:
    sys = (
        "You are Aryx, a knowledge-graph assistant. You explain product "
        "configuration, requirements, and enterprise data in plain, everyday "
        "English — the way you'd explain it to a colleague who isn't technical. "
        "Always answer from the GRAPH FACTS provided. "
        "Name the specific things you're talking about (products, values, "
        "relationships) but describe them in plain words, never technical or "
        "internal terminology. Be direct and specific — never hedge when facts "
        "are in front of you."
    )
    has_context = bool(context.strip())
    facts = context if has_context else "(none — no specific entity matched)"
    conv = _recent(history or [], limit=6)
    conv_block = f"\nCONVERSATION SO FAR:\n{conv}\n" if conv else ""

    # Grounded scope check (docs/CPQ_LLM_INTENT_FIRST_PLAN.md Fix 2, extended
    # 2026-07-28): originally only spent when GRAPH FACTS was empty. Confirmed
    # live this codepath previously fabricated plausible-sounding catalog
    # details (SVX Video RSM, currency options) for a genuinely unrelated
    # astrology question ("astra in astrological sense") — but that fabricated
    # answer came from a WEAK/SPURIOUS entity match the graph search DID
    # return (has_context was True), not from an empty result, so the
    # original has_context-gated check never even ran. The catalog-relevance
    # question ("is this question actually about product config/quoting at
    # all?") is independent of whether SOME entity happened to fuzzy-match —
    # always classify, and let a genuinely irrelevant question override
    # whatever facts were found.
    # docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §14 — pass the
    # recent conversation (already computed above as `conv`) so a mid-
    # session follow-up like "what is the error" can be recognized as
    # relevant when the prior turn was the engine's own gate error. The
    # OTHER call site (run_ask's fresh-turn router) intentionally does not
    # pass this — it has no session context to give. Ported onto
    # _llm_classify_is_ask_in_scope (not _llm_classify_is_cpq_question) —
    # this call site needs the BROADER scope gate (general enterprise/
    # catalog questions, not just quote/order intent); see that function's
    # own docstring for why reusing the narrow classifier here caused Ask
    # to refuse almost every question.
    is_cpq_relevant = _llm_classify_is_ask_in_scope(
        question, workspace_id, prior_context=conv,
    )
    logger.info(
        "cpq_qa_scope: has_context=%s for %r -> is_ask_in_scope=%s",
        has_context, question, is_cpq_relevant,
    )

    if not is_cpq_relevant:
        empty_rule = (
            "- The question is not about product configuration, quoting, or "
            "enterprise data at all → say plainly that this is outside what "
            "you track (product configuration and quoting), in one short "
            "sentence, EVEN IF something below happens to loosely match a "
            "word in the question. Do NOT invent or connect unrelated "
            "catalog details to answer it anyway.\n"
        )
    elif has_context:
        empty_rule = (
            "- GRAPH FACTS present → answer specifically, naming the entities, "
            "values, and relationships shown, in plain language.\n"
        )
    else:
        empty_rule = (
            "- GRAPH FACTS empty → use the OVERVIEW to describe what IS tracked "
            "and suggest a concrete follow-up question. "
            "Do NOT say 'no matching entities' or 'not stored'.\n"
        )

    # Session-value rule (docs/CPQ_LLM_INTENT_FIRST_PLAN.md Fix 3): only
    # added when the caller found a real filled value for an entity the
    # graph search resolved. Confirmed live this path previously answered
    # "the data doesn't show a specific frequency value being set" for a
    # question about an attr that WAS genuinely filled in this exact
    # session — GRAPH FACTS alone is the static catalog schema, never the
    # per-turn answered values, so this couldn't be told apart from
    # genuinely unfilled without this.
    session_values_block = ""
    session_value_rule = ""
    if session_values.strip():
        session_values_block = f"\nSESSION VALUES:\n{session_values}\n"
        session_value_rule = (
            "- If the question asks what something is currently SET TO, "
            "answer from SESSION VALUES when present — it reflects this "
            "customer's real selection for THIS quote, which the static "
            "GRAPH FACTS alone cannot show.\n"
        )

    user = (
        "Answer the QUESTION using the evidence below.\n\n"
        "Rules:\n"
        f"{session_value_rule}"
        f"{empty_rule}"
        "- Do NOT invent facts not shown in GRAPH FACTS.\n"
        "- Use CONVERSATION SO FAR to resolve pronouns and give continuity.\n"
        f"- Format: maximum {_MAX_ANSWER_LINES} lines. Lead with a direct "
        "one-line answer, then supporting detail in the order a person would "
        "naturally explain it. Use a short list only when multiple distinct "
        "items are being enumerated. Plain, everyday English — no technical "
        "or internal terms.\n\n"
        f"{overview}{conv_block}{session_values_block}\nGRAPH FACTS:\n"
        f"{facts if is_cpq_relevant else '(withheld — question is off-topic, see rule above)'}"
        f"\n\nQUESTION: {question}"
    )
    start = time.monotonic()
    text, it, ot = llm_runtime.chat("answer", sys, user, workspace_id=workspace_id)
    ms = int((time.monotonic() - start) * 1000)
    text = _strip_think(text)
    text, r_it, r_ot, r_ms = _enforce_plain_answer(text, question, workspace_id)
    return text, it + r_it, ot + r_ot, ms + r_ms
