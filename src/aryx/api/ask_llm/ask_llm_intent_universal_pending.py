"""Building the "what did the system just ask" prompt block for
`_llm_classify_intent_universal`, split out of `api/ask_api.py` (Phase 6/
11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-
09-03.md) purely to keep the sibling `ask_llm_classify_intent_universal.
py` under the line cap. Logic unchanged from the original inline block —
this fixes a live-confirmed hallucination (2026-07-28): fed the bare
reply "serviceType_astro" (answering a PRIOR turn's label-collision
question) with no pending-state context, the classifier invented a
plausible-sounding but nonexistent attribute ("Service Category")
instead of recognizing the literal reply.
"""

from __future__ import annotations

from typing import Any


def _build_pending_state_block(session: Any, by_vn: dict) -> str:
    """Every pending-state tracker CpqSession carries — not just
    `pending_variables[0]` — is surfaced here: a bare reply almost always
    answers ONE of these, never a fresh, freestanding request, and the
    model had no way to know that with only one line of context.
    """
    def _pending_desc(vn: str) -> str:
        a = by_vn.get(vn)
        return f"{a.display_label} (variable_name={vn})" if a else vn

    pending_lines: list[str] = []
    if session.pending_variables:
        pending_lines.append(
            f"- The system just asked about: {_pending_desc(session.pending_variables[0])}. "
            "A short/bare reply is almost certainly answering THIS."
        )
    if session.pending_change_collision_vns:
        _opts = ", ".join(_pending_desc(v) for v in session.pending_change_collision_vns)
        pending_lines.append(
            f"- The system just asked WHICH of these identically-labeled "
            f"attributes was meant: {_opts}. A reply naming one of these "
            "variable_names or an index number is answering THIS, not "
            "requesting a change to something else."
        )
    if session.pending_change_no_value_vn:
        pending_lines.append(
            f"- The system just asked what NEW VALUE to set for: "
            f"{_pending_desc(session.pending_change_no_value_vn)}. A short "
            "reply is almost certainly that value, not a fresh request."
        )
    if session.pending_clarify_vns:
        _opts = ", ".join(_pending_desc(v) for v in session.pending_clarify_vns)
        pending_lines.append(
            f"- The system just asked WHICH attribute was meant by a vague "
            f"request ({session.pending_clarify_question!r}): {_opts}. "
            "A short reply naming one of these labels, variable_names, or a "
            "list index is answering THAT clarify — not a fresh lookup."
        )
    if session.pending_label_collision_vns:
        _opts = ", ".join(_pending_desc(v) for v in session.pending_label_collision_vns)
        pending_lines.append(
            f"- The system just asked which of these identically-labeled "
            f"attributes a QUESTION was about: {_opts}."
        )
    return (
        "PENDING STATE — what the system just asked, before this message:\n"
        + "\n".join(pending_lines) + "\n\n"
        if pending_lines else ""
    )
