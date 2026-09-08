"""Label-collision detection for a system-initiated next question, the
decline-change-request regex, and the LLM disambiguation-question
composer, split out of `ask_api.py` (final sweep, Phase 11/11-phase
ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
`_label_collision_for` detects a shared display_label collision for the
engine's own auto-selected `pending[0]`, not a user-typed query —
`detect_label_collision` only ever fires against an explicit user
question. `_compose_disambiguation_question` (Amendment 16 Layer 2)
composes a natural clarifying question instead of a flat numbered-list
template; it NEVER invents an option and falls back to the static
template verbatim whenever the composed text is missing any real
candidate's identifying text. Logic unchanged from the original inline
definitions. `_cpq_engine` and `logger` are read through the ask_api
module object (not imported by name) since tests patch several ask_api
names by dotted path, and `_DECLINE_CHANGE_RE` is read the same way by
`ask_handle_cascade.py`.
"""

from __future__ import annotations

import re
from typing import Any

from aryx import llm_runtime


# Decline detector for a pending change-target prompt (docs/CPQ_SESSION_
# 2026_07_29_ISSUES_PLAN.md #2): "change product" -> "which value?" ->
# "I don't want to change product" was previously fed straight into
# apply_answer as an attempted (and failed) VALUE for Product, producing
# "I couldn't match that to a valid option" instead of recognizing the
# reply as a cancel. Deliberately narrow (only cancel-shaped phrasing) —
# never treat an ordinary short reply as a decline by accident.
_DECLINE_CHANGE_RE = re.compile(
    r"\b(?:"
    r"don'?t want to change|do not want to change|"
    r"don'?t want to|no change|never\s?mind|"
    r"keep (?:it|the current|the same)|leave (?:it|the current)|"
    r"cancel (?:that|this)?"
    r")\b",
    re.IGNORECASE,
)


def _label_collision_for(
    attr: Any, attrs: list, session: Any = None, pending: list | None = None,
) -> list | None:
    """Detect a shared display_label collision for a SYSTEM-initiated next
    question. Excludes candidates already resolved (in `session.filled`
    or `session.filled_multi`) when `session` is given, and candidates
    absent from `pending` when it's given — only a sibling the engine
    would actually ask next is a real collision. Returns the full list of
    same-labeled, still-unresolved attrs (2+) when `attr`'s label
    collides with others, else None.
    """
    matches = [a for a in attrs if a.display_label == attr.display_label]
    if session is not None:
        matches = [
            a for a in matches
            if a.variable_name not in session.filled
            and a.variable_name not in session.filled_multi
        ]
    if pending is not None:
        pending_vns = {a.variable_name for a in pending}
        matches = [a for a in matches if a.variable_name in pending_vns]
    if len({a.variable_name for a in matches}) >= 2:
        return matches
    return None


def _compose_disambiguation_question(
    question: str, prompt_topic: str, candidate_labels: list[str],
    already_known: dict[str, str], static_fallback: str, workspace_id: int,
) -> str:
    """Amendment 16 Layer 2 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md):
    compose a natural clarifying question instead of a flat numbered-list
    template, for the three ambiguous moments this doc scopes it to
    (label collision, model-leaf list, low-confidence pending-answer).
    NEVER invents an option; falls back to `static_fallback` verbatim
    whenever the LLM call raises, the response is empty, OR the composed
    text is missing any real candidate's identifying text.
    """
    from aryx.api import ask_api as _ask_api_module
    logger = _ask_api_module.logger
    if not candidate_labels:
        return static_fallback
    known_lines = "\n".join(f"- {k}: {v}" for k, v in already_known.items() if v)
    sys = (
        "You write ONE short, natural, conversational clarifying question "
        "for a customer configuring a product, given what they already "
        "said and a fixed list of real options they must choose between. "
        "Reflect back anything already known so they aren't asked to "
        "repeat it. List the exact options given, formatted naturally — "
        "never add, remove, rename, or invent an option. Reply with ONLY "
        "the question text (the option list may be part of it) — no JSON, "
        "no preamble, no explanation of what you're doing."
    )
    user = (
        f"CUSTOMER'S MOST RECENT MESSAGE: {question}\n\n"
        f"ALREADY KNOWN:\n{known_lines or '(nothing yet)'}\n\n"
        f"WHAT TO ASK ABOUT: {prompt_topic}\n\n"
        "REAL OPTIONS (use exactly these, do not invent others):\n"
        + "\n".join(f"- {c}" for c in candidate_labels)
    )
    try:
        text, _it, _ot = llm_runtime.chat("menial", sys, user, workspace_id=workspace_id)
        text = text.strip()
        if not text:
            return static_fallback
        norm_text = re.sub(r"[^a-z0-9]", "", text.lower())
        for label in candidate_labels:
            norm_label = re.sub(r"[^a-z0-9]", "", label.lower())
            if norm_label and norm_label not in norm_text:
                return static_fallback  # a real candidate got dropped — never trust this
        return text
    except Exception as exc:  # noqa: BLE001 — fallback must never crash the turn
        logger.debug("disambiguation composer failed: %r", exc)
        return static_fallback
