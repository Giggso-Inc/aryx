"""Splicing json/beautify/api_share fields into a CPQ turn's response,
split out of `api/ask_api.py` (Phase 9/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from
the original inline definition. `_cpq_engine`, `logger`, and several
not-yet-split ask_api.py names are read through the ask_api MODULE
object (not imported by name) since ask_api tests patch several of its
own module-level names by dotted path.
"""

from __future__ import annotations

import time
from typing import Any

from aryx.api.ask_response_building.ask_mandatory_block_splice import _beautify_mandatory_block, _labels_already_shown, _splice_mandatory_block_into_summary
from aryx.cpq.state import CpqSession

_SHARE_READY_MIN_FILLED = 3


def _attach_share_flags(result: dict[str, Any], req: "Any", reader: Any) -> None:
    """Splice json/beautify/api_share fields into a CPQ turn's response, in place.

    Single wrap point (called once from run_ask, not from every _run_cpq_turn
    return site) — recomputed every ready turn from current session state, never
    cached, since cascade can invalidate previously-filled attrs mid-conversation.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    session_data = result.get("session_data")
    if not session_data:
        return
    session = CpqSession.from_dict(session_data)
    filled_count = len(session.filled) + len(session.filled_multi)
    ready = filled_count >= _SHARE_READY_MIN_FILLED or session.status != "configuring"
    if not ready or not session.product_name:
        return
    # docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md — this whole
    # function was a real observability blind spot: it runs unconditionally
    # on every "ready" turn to populate the JSON/Beautify preview (whether
    # or not the customer ever opens either panel), and none of its own
    # cost was logged separately from whatever step happened to log next
    # afterward (e.g. a later evaluate_rules_loop's own load_hiding_rules
    # line). Bracketed here so this function's real cost is visible on its
    # own, not silently attributed to something else.
    _share_t0 = time.monotonic()
    attrs, _ = _cpq_engine.load_product_config(reader, req.workspace_id, session.product_name)
    _ask_api_module.logger.info(
        "cpq_perf: _attach_share_flags load_product_config took %.3fs",
        time.monotonic() - _share_t0,
    )
    # NOTE: hiding-rule auto-fix (docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md
    # §4.1) is not applied here — this is only the share-button preview
    # snapshot, and running apply_hiding_rules + a BmlEvaluator here would
    # mean a second, potentially Tier-2-LLM-backed evaluation pass on every
    # ready turn just for a preview. The real submission path
    # (_run_cpq_turn's Step 8 build_payload call) already applies it.
    #
    # Raven review on PR #142 (docs/APX_Next_RootCause_And_Fix_Report):
    # this preview payload is customer-visible (the web UI's JSON/share
    # button) and was still using build_payload's order_number-only
    # fallback, so it could show the exact wrong-sequence bug that PR
    # fixed elsewhere (e.g. Product listed before the Hardware Version
    # that gates it). Fixed by loading JUST the rule lists here — a plain
    # DB read via load_hiding_rules/load_recommendation_and_constraint_
    # rules, no script evaluation, no BmlEvaluator, no LLM calls — and
    # passing them to build_payload's `rules` param for ordering only.
    # This is a materially cheaper cost than the hiding-rule auto-fix this
    # function already deliberately skips, so it doesn't reintroduce the
    # round-trip this comment originally avoided.
    catalog_prefix = attrs[0].catalog_prefix if attrs else ""
    hiding_rules_preview = _cpq_engine.load_hiding_rules(
        req.workspace_id, catalog_prefix, session.product_name)
    rec_rules_preview, con_rules_preview = _cpq_engine.load_recommendation_and_constraint_rules(
        req.workspace_id, catalog_prefix)
    # Flow exclusions MUST apply here too (Issue 11 §5) — this is the web
    # UI's JSON-button payload, a separate emission path from the chat
    # "show me the json" preview and the Step-8 submission (both already
    # excluded). Confirmed live: without this, the button showed
    # modelname_all alongside productSelectionProduct_all (and, on model
    # flows, the skipped product selector). Cheap: layout scope is cached
    # per (workspace, catalog); no extra rule fetch.
    flow_exclusions = _cpq_engine.payload_flow_exclusions(
        req.workspace_id, catalog_prefix, attrs)
    payload = _cpq_engine.build_payload(
        session.filled, session.filled_source, session.filled_multi, attrs,
        hidden_vns=flow_exclusions,
        rules=[*hiding_rules_preview, *rec_rules_preview, *con_rules_preview],
        display_order=_cpq_engine.load_layout_display_order(req.workspace_id, catalog_prefix),
        product_quantity=session.product_quantity,
        scope_required_and_edited=True,
        workspace_id=req.workspace_id, catalog_prefix=catalog_prefix,
        # docs/CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T3 — the
        # customer's own original wording (CpqSession.product_anchor_
        # question) so Tier A's Hardware Version branch can consult the
        # real applicability check instead of forcing HW mandatory
        # regardless of whether it applies to this device.
        product_anchor_hint=session.product_anchor_question)
    result["json_response"] = payload
    result["json_button_flag"] = True
    _beautify_required_vns = _cpq_engine.mandatory_tier_c_vns(
        session.filled, req.workspace_id, catalog_prefix,
        attrs=attrs, filled_source=session.filled_source, filled_multi=session.filled_multi,
        display_order=_cpq_engine.load_layout_display_order(req.workspace_id, catalog_prefix),
        product_hint=session.product_anchor_question or "")
    result["beautify"] = _cpq_engine.beautify_text(
        session.product_name, session.display_filled, attrs, session.filled_source,
        required_vns=_beautify_required_vns,
        product_anchor_hint=session.product_anchor_question,
        workspace_id=req.workspace_id, catalog_prefix=catalog_prefix)
    result["beautify_rows"] = _cpq_engine.beautify_rows(
        session.product_name, session.display_filled, attrs, session.filled_source,
        required_vns=_beautify_required_vns,
        product_anchor_hint=session.product_anchor_question,
        workspace_id=req.workspace_id, catalog_prefix=catalog_prefix)
    result["beautify_button_flag"] = True
    result["api_share"] = payload if session.status != "configuring" else {}
    result["api_share_button_flag"] = session.status != "configuring"
    # Live-confirmed ask (2026-08-20): the chat answer's own "Mandatory
    # User Input" section must show the SAME facts Beautify's does for
    # this exact turn — force it to Beautify's own data rather than
    # trusting the summary's separately-computed category grouping to
    # agree (see `_splice_mandatory_block_into_summary`'s own docstring).
    #
    # Explicit ask (2026-08-20): unlike the JSON/Beautify BUTTONS above
    # (deliberately shown early, once `_SHARE_READY_MIN_FILLED` attrs are
    # filled, so a rep can preview mid-conversation), the SPLICE must
    # only fire on the "Configuration complete, awaiting confirm" turn --
    # `session.status == "awaiting_approval"` specifically, not merely
    # `!= "configuring"`. That looser check also matched "post_approval"
    # (set by `_handle_approval` once the customer says **confirm**),
    # so the spliced Mandatory User Input block kept appearing under the
    # post-confirm JSON payload response too -- a turn that should show
    # ONLY the submitted JSON, nothing else, per explicit ask. Before
    # that, the same looser check matched "configuring" turns with 3+
    # filled attrs and real questions still pending (`ready`, used for
    # the buttons, goes True on the filled-count threshold alone) --
    # splicing then put the block on intermediate "choose one" turns
    # too. Only "awaiting_approval" is the turn genuinely complete AND
    # still waiting on the customer, which is the one place Beautify's
    # own Mandatory list belongs in the chat summary.
    if result.get("answer") and session.status == "awaiting_approval":
        _already_shown = _labels_already_shown(result["answer"])
        _mandatory_block = _beautify_mandatory_block(
            result["beautify_rows"], _already_shown,
        )
        if _mandatory_block is not None:
            result["answer"] = _splice_mandatory_block_into_summary(
                result["answer"], _mandatory_block,
            )
