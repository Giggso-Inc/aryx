"""One structured universal-intent classification call per the Phase 0
schema, split out of `api/ask_api.py` (Phase 6/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic
unchanged from the original inline definition; the pending-state prompt
block lives in the sibling `ask_llm_intent_universal_pending.py` purely
to keep this file under the line cap. `logger` is read through the
ask_api MODULE object (not imported by name) for consistency with the
rest of this decomposition.
"""

from __future__ import annotations

import json
from typing import Any

from aryx import llm_runtime
from aryx.api.ask_llm.ask_llm_intent_universal_pending import _build_pending_state_block
from aryx.api.ask_catalog.ask_relevant_intent_candidates import _relevant_intent_candidates
from aryx.cpq.intent_schema.intent_schema import INTENT_RESULT_JSON_SCHEMA, IntentCategory, parse_intent_result

_INTENT_CATEGORY_LIST = ", ".join(c.value for c in IntentCategory)


def _llm_classify_intent_universal(
    question: str, attrs: list, session: Any, workspace_id: int,
) -> "tuple[Any | None, int, int]":
    """One structured classification call per the Phase 0 schema
    (`aryx.cpq.intent_schema.intent_schema`).

    Returns (result, prompt_tokens, completion_tokens) — 2026-07-28: token
    counts are threaded through so callers that actually DISPATCH on this
    classification (unlike Phase 1's shadow-mode logging, which only ever
    reads `result`) can report real usage instead of the hardcoded
    "cpq-engine, 0 tokens" every deterministic handler's response carries.
    Live-confirmed UX gap: the LLM-first path was correctly classifying
    and dispatching, but its response still showed 0 tokens/"cpq-engine",
    making it indistinguishable from the pure deterministic path even
    though a real LLM call drove the decision.

    Reuses `_relevant_intent_candidates` (the existing pre-filter every
    other `_llm_*` fallback in this file already relies on) to keep the
    candidate list on-topic and bounded even against an 800+-attr catalog
    (plan doc mitigation #6) — never the full attrs list unfiltered.

    The LLM is never asked for a `variable_name`/`item_value` — only a
    plain-language `target_description`/`new_value_description` per the
    schema's own two-layer design; resolving that description to a real
    catalog attr is `_resolve_target_description`'s job, not this
    function's. Fails closed (returns None) on any LLM/parse error, same
    discipline as every other Tier-2 fallback here.

    Two fixes (2026-07-28) for a live-confirmed hallucination in shadow-
    mode data: fed the bare reply "serviceType_astro" (answering a PRIOR
    turn's label-collision question), the classifier invented a plausible-
    sounding but nonexistent attribute ("Service Category") instead of
    recognizing the literal reply.

    1. Every pending-state tracker CpqSession carries — not just
       `pending_variables[0]` — is surfaced to the prompt: a bare reply
       almost always answers ONE of these, never a fresh, freestanding
       request, and the model had no way to know that with only one line
       of context.
    2. The prompt now explicitly tells the model to check the message
       against the CANDIDATES' OWN variable_name fields first when it
       looks like a raw identifier (snake/camelCase, no spaces) rather
       than natural language, and to prefer `ambiguous`/low confidence
       over inventing a plausible-sounding label when nothing matches
       literally — the same "never guess a real decision" discipline the
       deterministic detectors already follow.
    """
    from aryx.api import ask_api as _ask_api_module
    candidates = _relevant_intent_candidates(question, attrs)
    catalog_lines = []
    for a in candidates:
        current = session.filled_multi.get(a.variable_name) or session.filled.get(a.variable_name)
        opts = ", ".join(o.display_name for o in a.options[:15]) if a.options else "(free text)"
        catalog_lines.append(
            f"- \"{a.display_label}\" [{a.select_type}] (variable_name={a.variable_name}): "
            f"current={current!r}; options=[{opts}]"
        )
    by_vn = {a.variable_name: a for a in attrs}
    pending_block = _build_pending_state_block(session, by_vn)
    sys = (
        "You classify a user's message in an in-progress product configuration "
        "chatbot. Reply ONLY as JSON matching this exact schema (no other text):\n"
        + json.dumps(INTENT_RESULT_JSON_SCHEMA, indent=1) + "\n\n"
        f"Valid category values: {_INTENT_CATEGORY_LIST}.\n"
        "NEVER invent or guess a catalog identifier — target_description and "
        "new_value_description are PLAIN LANGUAGE descriptions of what the user "
        "means, never a raw field code. If you cannot confidently name a single "
        "clear target, or the message could plausibly mean 2+ different fields "
        "in the list below, use category=\"ambiguous\" and give a specific "
        "clarifying_question — never guess between plausible options.\n\n"
        "If the message itself looks like a raw identifier — snake_case or "
        "camelCase, no spaces, not a phrase a person would naturally type — "
        "check it against the candidates' own variable_name values FIRST "
        "(shown in parentheses below) before attempting any description. "
        "Never invent a plausible-sounding attribute name to explain an "
        "identifier you don't recognize; if it doesn't match any listed "
        "variable_name and there's no PENDING STATE explaining it, use "
        "confidence=\"low\" and category=\"ambiguous\" instead.\n\n"
        "Use category=\"session_status_query\" ONLY when the message asks "
        "about the CONVERSATION/PROCESS itself — e.g. \"what's next?\", "
        "\"what is the next step?\", \"where am I?\", \"what should I do "
        "now?\", \"what do you need from me?\" — never when it asks about "
        "catalog content, even content that happens to use the word "
        "\"next\" (e.g. \"what's the next hardware version model\" is "
        "ATTR_QUERY/QA_QUESTION about the catalog, NOT session_status_query "
        "— it names a real thing in the catalog, not the conversation "
        "itself). If in doubt whether a message is about the process or "
        "the catalog, prefer the catalog category (qa_question/ambiguous) "
        "— session_status_query is deliberately narrow."
    )
    user = (
        f"{pending_block}"
        "ATTRIBUTES CURRENTLY RELEVANT (label [type] (variable_name=...): "
        "current=...; options=[...]):\n"
        + "\n".join(catalog_lines) +
        f"\n\nUSER MESSAGE: {question}"
    )
    try:
        text, _it, _ot = llm_runtime.chat("menial", sys, user, workspace_id=workspace_id)
        s, e = text.find("{"), text.rfind("}")
        parsed = json.loads(text[s:e + 1])
    except Exception as exc:  # noqa: BLE001 — shadow call must never crash the turn
        _ask_api_module.logger.debug("cpq_shadow_intent: llm call or parse failed: %r", exc)
        return None, 0, 0
    return parse_intent_result(parsed), _it, _ot
