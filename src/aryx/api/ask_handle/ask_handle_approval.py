"""STEP 8 — explicit approval → generate BOM payload, split out of
`api/ask_api.py` (Phase 5/11-phase ask_api decomposition, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original
inline definition; the stale-constraint/genuine-conflict branches live
in the sibling `ask_approval_stale_violations.py` purely to keep this
file under the line cap. `_cpq_engine` and `_persist_cpq_history` are
read through the ask_api MODULE object (not imported by name) since
ask_api tests patch several of its own module-level names by dotted
path.
"""

from __future__ import annotations

import json
from typing import Any

from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_approval_stale_violations import (
    _handle_approval_gate_conflict,
    _handle_approval_stale_reask,
)
from aryx.cpq.bom_gate.bom_gate import validate_before_payload
from aryx.cpq import rule_trace


def _handle_approval(
    req: "Any", session: Any, attrs: list,
    hiding_rules: list, rec_rules: list, con_rules: list, bml_eval: Any,
    hints: dict | None = None,
) -> dict[str, Any]:
    """STEP 8 — explicit approval → generate BOM payload.

    Factored out of the regex path (docs/CPQ_REGEX_VS_LLM_ANCHOR_
    GUARDRAIL_AUDIT_2026_08_12.md `APPROVAL` dispatch) verbatim — same
    final BOM gate (constraint re-run + provenance hard-fail), same
    rule-conflict / stale-constraint-reask / bom-gate-blocked branches,
    same payload construction — so the LLM-dispatched path and the
    regex-triggered path can never drift into two different approval
    behaviors. Recomputes `catalog_prefix` and `_hidden_for_payload`
    internally rather than accepting them as params, since this is now
    the single source of truth both callers share — deliberately NOT
    threading the outer turn's already-computed values in, so a future
    change to either payload-drop rule only ever has one place to edit.

    `hints` (default `{}`) only affects the final approved response's
    cosmetic `terms` field — never anything the BOM gate itself checks.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    hints = hints or {}
    catalog_prefix = attrs[0].catalog_prefix if attrs else ""
    _hidden_for_payload = _cpq_engine.apply_hiding_rules(
        attrs, session.filled, hiding_rules, bml_eval, filled_multi=session.filled_multi)[2]
    _hidden_for_payload = _hidden_for_payload | _cpq_engine.payload_flow_exclusions(
        req.workspace_id, catalog_prefix, attrs)
    if session.model_leaf_resolved:
        _hidden_for_payload = _hidden_for_payload | _cpq_engine.product_label_noise_vns(
            attrs, hiding_rules, rec_rules, con_rules)

    # Final BOM gate — constraint re-run + provenance hard-fail. Never
    # emit a payload that fails verification.
    catalog_prefix_gate = attrs[0].catalog_prefix if attrs else ""
    bml_gate = _cpq_engine.build_bml_evaluator(req.workspace_id, catalog_prefix_gate)
    gate = validate_before_payload(_cpq_engine, attrs, session, con_rules, bml_gate)
    if not gate.ok and gate.stale_violations:
        _conflict_response = _handle_approval_gate_conflict(req, session, attrs, gate)
        if _conflict_response is not None:
            return _conflict_response
        return _handle_approval_stale_reask(req, session, attrs, gate)
    if not gate.ok:
        session.complete = False
        session.status = "awaiting_approval"
        _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, gate.catch_message)
        return {
            "answer": gate.catch_message, "terms": [], "tools_called": ["cpq_bom_gate_blocked()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }
    session.status = "post_approval"
    session.complete = True
    # Real confirm signal for the rule-execution trace — session.status
    # is never actually "approved" anywhere in this codebase;
    # session.complete becoming True here, at BOM payload generation, is
    # the true one-time confirm event.
    rule_trace.seal(session.run_id, status="post_approval")
    # `payload` is scoped (Tier A/B: mandatory + user-answered attrs only)
    # -- both the REAL submitted BOM (returned as `cpq_payload` below) and
    # the chat display use this same scoped view.
    #
    # Live-verified twice against MSI staging: (1) api-sales-ui-2008.log/
    # -2108.log, latest reproduction 2026-08-21 03:46 -- the unscoped/full
    # payload (~40 fields, matching what this function used to send) is
    # rejected by MSI's real `_configure` action with HTTP 400 on
    # additionalSystemEnhancementFeatureType_astro, an auto-filled catalog
    # default never confirmed by the customer. (2) The same scoped
    # 6-field payload sent standalone via Postman to the identical
    # `_configure` endpoint returns 200 OK, with MSI's own response
    # showing it self-derives every other attribute via its own rule
    # engine -- MSI does not need or want Aryx to send its own
    # auto-filled defaults for those fields.
    #
    # `build_payload`'s own docstring previously assumed "a real BOM
    # submission must stay unscoped/full"; that assumption is superseded
    # by this live MSI behavior. A prior revision of this fix (reverted)
    # scoped only the chat DISPLAY, leaving the real submission unscoped
    # per that assumption -- Raven Review flagged the scoped submission
    # as silently dropping rule-resolved values (e.g. Wireless Carrier);
    # in the live flow, Wireless Carrier is always a genuine Tier A/B
    # (customer-asked) attribute, never rule-only, so it is not affected.
    payload = _cpq_engine.build_payload(
        session.filled, session.filled_source, session.filled_multi, attrs,
        hidden_vns=_hidden_for_payload,
        rules=[*hiding_rules, *rec_rules, *con_rules],
        display_order=_cpq_engine.load_layout_display_order(req.workspace_id, catalog_prefix),
        product_quantity=session.product_quantity,
        scope_required_and_edited=True,
        workspace_id=req.workspace_id, catalog_prefix=catalog_prefix)
    answer = f"```json\n{json.dumps(payload, indent=2)}\n```"
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": list(hints.values()), "tools_called": ["cpq_payload_approved()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": payload,
    }
