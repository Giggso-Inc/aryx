""""Show me the JSON" preview and explicit-decline response builders,
split out of `ask_api.py` (final sweep, Phase 11/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
`_build_json_preview_response` was factored out of the regex path
(docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md Phase 4) so
the RESPONSE_MODE_REQUEST dispatch branch can share the exact same
response shape — preview only, never sets cpq_payload, never mutates
session.status. `_handle_decline` (ISSUE-002 fix, docs/CPQ_E2E_ISSUES_
001_002_003_004_FIX_PLAN_2026_08_17.md) is deliberately much simpler
than `_handle_approval`: a decline is a pure session-state rollback, not
a mutating action against the catalog, and uses a distinct `cpq_
decline()` tool name so it's traceable in logs as the opposite outcome
from approval. Logic unchanged from the original inline definitions.
`_cpq_engine`, `_cpq_summary_text`, and `_persist_cpq_history` are read
through the ask_api module object (not imported by name) since tests
patch several ask_api names by dotted path.
"""

from __future__ import annotations

import json
from typing import Any

from aryx.api.ask_response_building.ask_cpq_summary_text import _cpq_summary_text
from aryx.api import ask_core_helpers as _ask_core_helpers_module


def _build_json_preview_response(
    req: "Any", session: Any, attrs: list,
    hiding_rules: list, rec_rules: list, con_rules: list, bml_eval: Any,
) -> dict[str, Any]:
    """"Show me the JSON" preview while awaiting approval. Recomputes
    `catalog_prefix`/hidden-attr set internally, same reasoning as
    `_handle_approval` — one source of truth both callers share.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    catalog_prefix = attrs[0].catalog_prefix if attrs else ""
    hidden_for_payload = _cpq_engine.apply_hiding_rules(
        attrs, session.filled, hiding_rules, bml_eval, filled_multi=session.filled_multi)[2]
    hidden_for_payload = hidden_for_payload | _cpq_engine.payload_flow_exclusions(
        req.workspace_id, catalog_prefix, attrs)
    if session.model_leaf_resolved:
        hidden_for_payload = hidden_for_payload | _cpq_engine.product_label_noise_vns(
            attrs, hiding_rules, rec_rules, con_rules)
    preview_payload = _cpq_engine.build_payload(
        session.filled, session.filled_source, session.filled_multi, attrs,
        hidden_vns=hidden_for_payload,
        rules=[*hiding_rules, *rec_rules, *con_rules],
        display_order=_cpq_engine.load_layout_display_order(req.workspace_id, catalog_prefix),
        product_quantity=session.product_quantity,
        scope_required_and_edited=True,
        workspace_id=req.workspace_id, catalog_prefix=catalog_prefix)
    rule_ids_preview = _cpq_engine.rule_governed_ids(
        attrs, hiding_rules, rec_rules, con_rules)
    summary = _cpq_summary_text(
        session.display_filled, attrs, rule_ids_preview,
        session.product_name, req.workspace_id, sources=session.filled_source,
        product_quantity=session.product_quantity, filled=session.filled,
    )
    answer = (
        (f"{summary}\n\n" if summary else "")
        + f"Here's the full configuration for **{session.product_name}** — "
          f"**preview, not final**:\n\n"
        f"```json\n{json.dumps(preview_payload, indent=2)}\n```\n\n"
        f"Say **confirm** to submit, or describe any changes."
    )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_json_preview()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        "preview": True,
    }


def _handle_decline(
    req: "Any", session: Any,
) -> dict[str, Any]:
    """Explicit rejection of an awaiting-approval configuration. Returns
    the session to `configuring` (only if it isn't already there — a
    decline sent from any other status is still an honest no-op
    acknowledgment, never an error).
    """
    if session.status != "configuring":
        session.status = "configuring"
    session.complete = False
    answer = "Understood — not submitting yet. What would you like to change?"
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_decline()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
