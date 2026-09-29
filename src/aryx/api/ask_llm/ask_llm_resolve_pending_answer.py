"""LLM fallback for STEP 5's pending-answer path, split out of `api/
ask_api.py` (Phase 6/11-phase ask_api decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original inline
definition.
"""

from __future__ import annotations

import logging
from typing import Any

from aryx.api.ask_llm.ask_llm_intent_core import _llm_classify_intent_core

logger = logging.getLogger(__name__)


def _llm_resolve_pending_answer(
    question: str, pending_attr: Any, workspace_id: int,
) -> dict[str, Any] | None:
    """LLM fallback for STEP 5's pending-answer path (Amendment 2 Gap A,
    docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md), tried only after
    apply_answer's fragment/word-boundary matching finds nothing.

    Live-confirmed need (2026-07-26): a long, natural, multi-intent
    sentence bundling the product name together with subscription type,
    quantity, and package tier never fragment-matches any of a long
    option list, even though a human reads the intended option
    immediately. Scoped to ONLY the one pending attr's own real options —
    never the full session or raw JSON — same never-guess discipline as
    every other Tier-2 fallback in this file: a returned value outside the
    attr's real option list is discarded, never trusted.

    Confidence-gated (decided 2026-07-24): a sentence can be genuinely
    ambiguous between two real, valid options in the same list — that's a
    judgment error, not hallucination, and scoping alone can't catch it.
    The prompt asks for a confidence signal alongside its pick; low
    confidence returns the narrowed candidate list instead of the pick
    itself, so the caller shows those for the customer to confirm rather
    than silently committing to a guess between two valid options.

    Returns {"iv": item_value, "disp": display_name, "confidence": "high"}
    on a confident, validated pick; {"confidence": "low", "candidates":
    [display_name, ...]} when the model itself signals low confidence;
    None on any failure (no options, LLM error, invented value, etc).

    Includes each option's internal item_value alongside its display_name
    (Amendment 7 follow-up, decided 2026-07-26): some catalogs' real
    option text is a marketing alias with no textual resemblance to what
    a customer actually says (confirmed live — CommandCentral Aware
    2024's own Product option displays as "Direct Streaming", the
    item_value is "COMMANDCENTRAL AWARE2"). Showing only display_name
    made a plainly-answerable sentence unresolvable in principle, not
    just in practice — the model had no path to the right answer at all.
    Matching either field is accepted; item_value is never itself shown
    to the customer, only used to widen what the model can recognize.
    """
    if not pending_attr.options:
        return None
    # CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T8: same silent-truncation
    # observability fix as the other LLM-facing option-list caps in this
    # codebase -- not changing the cap, just making it visible.
    if len(pending_attr.options) > 200:
        logger.warning(
            "cpq_llm_options_truncated: variable_name=%s option_count=%d "
            "cap=200 -- %d option(s) never shown to the LLM",
            pending_attr.variable_name, len(pending_attr.options),
            len(pending_attr.options) - 200,
        )
    opt_lines = "\n".join(
        f"- {o.display_name} (internal code: {o.item_value})"
        if o.item_value.lower() != o.display_name.lower() else f"- {o.display_name}"
        for o in pending_attr.options[:200]
    )
    sys = (
        "You extract which option a user's message names for a single "
        "pending question, even when the message is a long sentence "
        "bundling several unrelated details together. Some options show "
        "an internal code in parentheses — the customer may say something "
        "closer to that code than to the display name (e.g. a product's "
        "internal/marketing name). Only pick from the OPTIONS list given "
        "— never invent one. If the message could plausibly mean two or "
        "more of the real options, set confidence to low and list the "
        "ones it could be; only set confidence to high when exactly one "
        "option is clearly named."
    )
    user = (
        f"QUESTION BEING ANSWERED: {pending_attr.display_label}\n\n"
        f"OPTIONS:\n{opt_lines}\n\n"
        f"USER MESSAGE: {question}\n\n"
        'Reply ONLY as JSON: {"value": "<exact display name from the list, or empty>", '
        '"confidence": "high"|"low", '
        '"candidates": ["<display name>", ...] (only when confidence is low)}'
    )
    valid_by_lower = {o.display_name.lower(): o for o in pending_attr.options}

    def _validate(parsed: dict) -> dict[str, Any] | None:
        confidence = parsed.get("confidence")
        if confidence == "low":
            raw_candidates = parsed.get("candidates") or []
            candidates = [c for c in raw_candidates if isinstance(c, str) and c.lower() in valid_by_lower]
            if len(candidates) < 2:
                return None
            return {"confidence": "low", "candidates": candidates}
        value = parsed.get("value") or ""
        opt = valid_by_lower.get(value.lower())
        if confidence != "high" or opt is None:
            return None
        return {"confidence": "high", "iv": opt.item_value, "disp": opt.display_name}

    return _llm_classify_intent_core(sys, user, workspace_id, _validate)
