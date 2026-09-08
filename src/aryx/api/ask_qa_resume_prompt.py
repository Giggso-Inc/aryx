"""Building the config-resume prompt appended after a Q&A answer, split
out of `_handle_cpq_qa` (Phase 8/11-phase ask_api decomposition, docs/
RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) purely to keep the sibling
`ask_handle_cpq_qa.py` under the line cap. Logic unchanged from the
original inline block. `_cpq_engine` is read through the ask_api MODULE
object (not imported by name) since at least one test replaces the
whole singleton via `patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module


def _build_qa_resume_prompt(session: Any, attrs: list, resume_review: bool) -> str:
    """Appends a resume prompt so the user knows where to continue."""
    _cpq_engine = _ask_api_module._cpq_engine
    if resume_review:
        return "\n\n---\n\n" + _cpq_engine.build_review_prompt(
            session.product_name, attrs, session.display_filled,
        )
    if session.pending_variables:
        pending_attr = next(
            (a for a in attrs if a.variable_name == session.pending_variables[0]), None,
        )
        if pending_attr:
            return (
                "\n\n---\n\n*Resuming your configuration...*\n\n"
                + _cpq_engine.next_question_prompt(pending_attr, attrs=attrs)
            )
    return ""
