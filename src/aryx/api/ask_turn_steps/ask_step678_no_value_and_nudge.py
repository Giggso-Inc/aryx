"""Change-verb-no-value detection and the final review-status catch-all
nudge, split out of `_run_cpq_turn_inner` (Phase 10/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Recognized change-verb naming an already-filled attr but with no
resolvable new value ("change hardware version", "change product") asks
which value instead of falling through to the generic nudge
(docs/CPQ_MID_CONFIG_CHANGE_REQUEST_PLAN.md Related finding 1). Could
not parse as approval, Q&A, change, or JSON request — nudge with the
verbose summary, NOT the raw JSON (§6/Phase K: JSON stays on-demand
only). Logic unchanged from the original inline block. Every ask_api
name below is read through the module object (not imported by name)
since tests patch several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_response_building.ask_build_no_value_response import _build_no_value_response
from aryx.api.ask_response_building.ask_cpq_summary_text import _cpq_summary_text
from aryx.api import ask_core_helpers as _ask_core_helpers_module


def _step6_no_value_or_nudge(
    req: "Any", session: Any, attrs: list, hiding_rules: list, rec_rules: list,
    con_rules: list, bml_eval: Any,
) -> dict[str, Any]:
    """Always returns a response dict — the final catch-all of STEP 6/7/8
    routing once every other detector has come up empty.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    _no_value_attr = _cpq_engine.detect_change_target_without_value(
        req.question, attrs, session.filled,
    )
    if _no_value_attr:
        return _build_no_value_response(
            req, session, attrs, _no_value_attr, con_rules, bml_eval,
            "cpq_change_target_no_value",
        )

    rule_ids_nudge = _cpq_engine.rule_governed_ids(attrs, hiding_rules, rec_rules, con_rules)
    summary = _cpq_summary_text(
        session.display_filled, attrs, rule_ids_nudge,
        session.product_name, req.workspace_id, sources=session.filled_source,
        product_quantity=session.product_quantity, filled=session.filled,
    )
    answer = (
        f"I didn't quite catch that. Here is the current configuration for "
        f"**{session.product_name}**:\n\n"
        + (f"{summary}\n\n" if summary else "")
        + f"Click **JSON** below to see the full payload, "
          f"say **confirm** to submit, or describe what to change."
    )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_review_nudge()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
