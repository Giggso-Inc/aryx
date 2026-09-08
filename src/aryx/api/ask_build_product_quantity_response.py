"""Applying a confirmed overall product-quantity change and building the
response, split out of `api/ask_api.py` (Phase 3/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic
unchanged from the original inline definition. `_cpq_engine`, `logger`,
and `_persist_cpq_history` are read through the ask_api MODULE object
(not imported by name) since ask_api tests patch several of its own
module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_build_show_summary_response import _build_show_summary_response
from aryx.cpq.engine import (
    MAX_PRODUCT_QUANTITY, MIN_PRODUCT_QUANTITY, is_valid_product_quantity,
)


def _build_product_quantity_change_response(
    req: "Any", session: Any, reader: Any,
    value: int | None, decimal_value: str | None = None,
) -> dict[str, Any]:
    """Apply a confirmed overall product-quantity change (or, when `value`
    and `decimal_value` are both None, just report the current one) and
    build the response.

    Factored out of the STEP-6 quantity gate (docs/CPQ_LLM_INTENT_FIRST_
    UNIVERSAL_PLAN.md §8 Phase 4) so the LLM-first dispatcher's new
    PRODUCT_QUANTITY_CHANGE branch shares the exact same validation and
    "show full summary once complete" logic instead of duplicating it —
    same discipline as `_build_attr_query_response` factoring out
    ATTR_QUERY's shared response shape.
    """
    from aryx.api import ask_api as _ask_api_module
    if decimal_value is not None:
        # PR #186 review, medium: an explicit decimal ("change quantity to
        # 10.0") gets its own dedicated rejection quoting exactly what the
        # customer typed — never the wrong, confusing digit the old
        # regex-backtracking bug used to surface here ("0" instead of "10.0").
        answer = (
            f"**{decimal_value}** isn't a valid quantity — it "
            f"needs to be a whole number from {MIN_PRODUCT_QUANTITY} to "
            f"{MAX_PRODUCT_QUANTITY:,}, not a decimal. Current quantity is "
            f"still **{session.product_quantity}**."
        )
        _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [],
            "tools_called": ["cpq_product_quantity_rejected()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }
    if value is not None and not is_valid_product_quantity(value):
        # An explicit, invalid request ("change quantity to -5"/"...to 0")
        # gets a real rejection, never a silent ignore or a silently-
        # accepted nonsense value — the customer asked for something
        # specific and needs to know why it didn't happen.
        answer = (
            f"**{value}** isn't a valid quantity — it needs to be "
            f"a whole number from {MIN_PRODUCT_QUANTITY} to "
            f"{MAX_PRODUCT_QUANTITY:,}. Current quantity is still "
            f"**{session.product_quantity}**."
        )
        _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [],
            "tools_called": ["cpq_product_quantity_rejected()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }
    if value is not None:
        session.product_quantity = value
    # Live-verified gap, 2026-08-13: a quantity change used to return ONLY
    # "Quantity → N", with no updated configuration summary — every other
    # attribute change shows the running configuration once it's complete.
    if not session.pending_variables:
        _qty_summary_resp = _build_show_summary_response(req, session, reader)
        if _qty_summary_resp is not None:
            _qty_summary_resp["answer"] = (
                f"**Quantity** → {session.product_quantity}\n\n"
                + _qty_summary_resp["answer"]
            )
            _qty_summary_resp["tools_called"] = ["cpq_product_quantity()"]
            return _qty_summary_resp
    answer = f"**Quantity** → {session.product_quantity}"
    # docs/CPQ_QA_RESUME_CONCATENATION_PLAN_2026_08_18.md follow-up: a
    # customer applying a quantity change while a different question is
    # still pending (e.g. Hardware Version, never answered) got no
    # reminder at all that it's still awaiting a reply -- unlike every
    # QA-answer path (_handle_cpq_qa), which always appends this same
    # "Resuming your configuration..." block when something is pending.
    # Silently losing track of a pending question is worse than a QA
    # answer never mentioning it, so this mirrors that existing,
    # already-battle-tested resume block exactly rather than inventing a
    # second wording. Never let a lookup failure here block the quantity
    # change itself -- the change is already applied above.
    if session.pending_variables:
        try:
            _qty_resume_attrs, _ = _ask_api_module._cpq_engine.load_product_config(
                reader, req.workspace_id, session.product_name,
            )
        except Exception as exc:  # noqa: BLE001
            _ask_api_module.logger.debug(
                "cpq quantity resume-reminder: load_product_config failed: %r", exc,
            )
            _qty_resume_attrs = []
        _qty_pending_attr = next(
            (a for a in _qty_resume_attrs if a.variable_name == session.pending_variables[0]),
            None,
        )
        if _qty_pending_attr is not None:
            answer += (
                "\n\n---\n\n*Resuming your configuration...*\n\n"
                + _ask_api_module._cpq_engine.next_question_prompt(
                    _qty_pending_attr, attrs=_qty_resume_attrs,
                )
            )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_product_quantity()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
