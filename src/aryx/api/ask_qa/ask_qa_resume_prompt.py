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

from aryx.raven_log import raven_log


def _log_resume(session: Any, opt: str, reason: str, **ctx: Any) -> None:
    """DEBUG record for which resume block (if any) follows the Q&A answer."""
    raven_log("DEBUG", "P4", "ask.qa.resume_prompt selected", context={
        "selected_option": opt, "available_options": ["review", "resume_pending", "none"],
        "reason_code": reason, "turn": getattr(session, "turn", None),
        "run_id": getattr(session, "run_id", None), "road": "qa", **ctx})


def _build_qa_resume_prompt(session: Any, attrs: list, resume_review: bool) -> str:
    """Appends a resume prompt so the user knows where to continue."""
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    if resume_review:
        _log_resume(session, "review", "RESUME_REVIEW")
        return "\n\n---\n\n" + _cpq_engine.build_review_prompt(
            session.product_name, attrs, session.display_filled,
        )
    if session.pending_variables:
        pending_attr = next(
            (a for a in attrs if a.variable_name == session.pending_variables[0]), None,
        )
        if pending_attr:
            _log_resume(session, "resume_pending", "PENDING_ATTR_FOUND",
                        pending_vn=getattr(pending_attr, "variable_name", None))
            return (
                "\n\n---\n\n*Resuming your configuration...*\n\n"
                + _cpq_engine.next_question_prompt(pending_attr, attrs=attrs)
            )
    _log_resume(session, "none", "PENDING_ATTR_NOT_FOUND" if session.pending_variables else "NOTHING_PENDING")
    return ""
