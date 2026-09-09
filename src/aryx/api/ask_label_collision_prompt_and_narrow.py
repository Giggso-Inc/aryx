"""Label-collision disambiguation-prompt rendering and relevance-based
narrowing, split out of `ask_api.py` (final sweep, Phase 11/11-phase
ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
`_label_collision_prompt` renders the disambiguation prompt — composed
conversationally via the LLM (Amendment 16 Layer 2) when possible,
falling back to the original flat template otherwise — always via
`disambiguated_label()` so the raw internal `variable_name` never leaks
(live-confirmed gap, 2026-08-24). `_narrow_label_collision` (Amendment 2
Gap B) narrows a collision candidate list by relevance to the question
before presenting it, but never narrows to a single candidate (an
auto-resolve this plan explicitly deferred) and never narrows to zero.
Logic unchanged from the original inline definitions. `_cpq_engine` and
`_compose_disambiguation_question` are read through the ask_api module
object (not imported by name) since tests patch several ask_api names
by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_catalog.ask_relevant_intent_candidates import _WORD_RE

from aryx.api.ask_label_collision_detect_and_compose import _compose_disambiguation_question


def _label_collision_prompt(
    collision: list, session: Any,
    question: str = "", workspace_id: int = 1,
) -> str:
    """Render the disambiguation prompt for a label collision. `question`/
    `workspace_id` default to values that make the fallback path behave
    identically to before Layer 2 existed, for any caller not yet updated
    to pass them.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    labels = {
        a.variable_name: _cpq_engine.disambiguated_label(a, collision)
        for a in collision
    }
    lines = "\n".join(
        f"- **{labels[a.variable_name]}**"
        f"{f' (currently: {session.display_filled.get(a.variable_name)})' if session.display_filled.get(a.variable_name) else ''}"
        for a in collision
    )
    static_fallback = (
        f"There are {len(collision)} different attributes labeled "
        f"**\"{collision[0].display_label}\"** in this catalog — which one "
        f"did you mean?\n\n{lines}"
    )
    if not question:
        return static_fallback
    return _compose_disambiguation_question(
        question, f'which attribute they mean by "{collision[0].display_label}"',
        [labels[a.variable_name] for a in collision],
        {"Country": getattr(session, "country", ""),
         "Product": getattr(session, "product_name", "")},
        static_fallback, workspace_id,
    )


def _narrow_label_collision(question: str, collision: list) -> list:
    """Narrow a label-collision candidate list by relevance to the
    question before presenting it (Amendment 2 Gap B). Returns the
    narrowed list (only the top-scoring candidates) when the question's
    vocabulary overlaps at least one candidate's label/options; returns
    the original, unnarrowed list when nothing overlaps at all, or when
    narrowing would collapse it below 2 candidates — narrowing the shown
    list is safe (it still asks), auto-resolving to one is not.
    """
    q_words = set(_WORD_RE.findall(question.lower()))
    if not q_words:
        return collision
    shared_label_words = set(_WORD_RE.findall(collision[0].display_label.lower()))
    scored = []
    for a in collision:
        vocab = set()
        for o in a.options:
            vocab |= set(_WORD_RE.findall(o.display_name.lower()))
        vocab -= shared_label_words
        overlap = len(q_words & vocab)
        scored.append((overlap, a))
    top_score = max(score for score, _a in scored)
    if top_score == 0:
        return collision
    narrowed = [a for score, a in scored if score == top_score]
    if len(narrowed) < 2:
        return collision
    return narrowed
