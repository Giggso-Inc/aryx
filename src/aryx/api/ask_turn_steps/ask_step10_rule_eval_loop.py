"""Orchestrator for STEP 5b (blocked-removal gap) and STEP 3 (the
hide/recommend/constrain rule-evaluation loop), split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Each sub-stage lives in
a sibling `ask_step10_*.py` file purely to keep this orchestrator under
the line cap. Amendment 10 follow-up: once a model-leaf is resolved,
every attr sharing that display_label is proven irrelevant/generic for
this catalog — skipped from asking via `skip_always_ask`, the same
mechanism the pre-existing model/product mutual-exclusivity logic uses
for the single-leaf case. Logic and stage order unchanged from the
original inline block.
"""

from __future__ import annotations

import time
from typing import Any

from aryx.api.ask_turn_steps.ask_step10_blocked_removal import _step10_blocked_removal_gap
from aryx.api.ask_turn_steps.ask_step10_commit_and_drain import _step10_commit_and_drain
from aryx.api.ask_turn_steps.ask_step10_recompute_pending import _step10_recompute_pending
from aryx.api.ask_turn_steps.ask_step10_sibling_and_multi_hint import _step10_enforce_siblings_and_multi_hint
from aryx.raven_log import raven_log


def _step10_run_rule_eval_loop(
    req: "Any", session: Any, attrs: list, hints: dict, hiding_rules: list,
    rec_rules: list, con_rules: list, validation_rules: list, bml_eval: Any,
    catalog_prefix: str, negated_vns: set, mode_request: str | None,
    pending_var: str | None,
) -> "tuple[dict[str, Any] | None, list, dict, dict, list, dict, set, str]":
    """Returns (early_response, visible_attrs, filled, display_filled,
    pending, constrained_opts, rule_ids, dropped_note). `early_response`
    is non-None when STEP 5b's blocked-removal gap fully handled this
    turn; the caller must return it immediately when present, in which
    case every other value is a placeholder empty/None.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    logger = _ask_api_module.logger

    _step10_early_response = _step10_blocked_removal_gap(
        req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval,
        catalog_prefix, mode_request,
    )
    if _step10_early_response is not None:
        raven_log("DEBUG", "P4", "ask.recompute.loop exited before rule eval", context={
            "selected_option": "blocked_removal_response",
            "available_options": ["blocked_removal_response", "rule_eval_complete"],
            "reason_code": "BLOCKED_REMOVAL_HANDLED", "turn": getattr(session, "turn", None)})
        return _step10_early_response, [], {}, {}, [], {}, set(), ""

    _step3_t0 = time.monotonic()
    logger.info("cpq_step: step3_rule_eval start run_id=%s", session.run_id)
    prev_filled_snapshot = dict(session.filled)
    prev_filled_multi_snapshot = {k: list(v) for k, v in session.filled_multi.items()}
    dropped_multi: dict[str, list[str]] = {}
    skip_always_ask = _cpq_engine.resolve_always_ask_skips(
        req.workspace_id, catalog_prefix, attrs)
    if session.model_leaf_resolved:
        skip_always_ask = skip_always_ask | _cpq_engine.product_label_noise_vns(
            attrs, hiding_rules, rec_rules, con_rules)

    visible_attrs, filled, display_filled, pending, constrained_opts, rule_ids = (
        _step10_recompute_pending(
            hints, attrs, session, hiding_rules, rec_rules, con_rules, bml_eval,
            dropped_multi, negated_vns, skip_always_ask, validation_rules, req,
            catalog_prefix,
        ))

    visible_attrs, filled, display_filled, pending, constrained_opts, rule_ids = (
        _step10_enforce_siblings_and_multi_hint(
            req, session, attrs, hints, visible_attrs, filled, display_filled,
            pending, constrained_opts, rule_ids, rec_rules, con_rules, hiding_rules,
            bml_eval, dropped_multi, negated_vns, skip_always_ask, validation_rules,
            catalog_prefix,
        ))

    dropped_note, pending = _step10_commit_and_drain(
        session, attrs, visible_attrs, filled, display_filled, pending, dropped_multi,
        prev_filled_snapshot, prev_filled_multi_snapshot, pending_var, _step3_t0,
    )

    raven_log("DEBUG", "P4", "ask.recompute.loop rule eval finished", context={
        "selected_option": "rule_eval_complete",
        "available_options": ["blocked_removal_response", "rule_eval_complete"],
        "reason_code": "PENDING_REMAINING" if pending else "NOTHING_PENDING",
        "skip_always_ask_count": len(skip_always_ask or ()),
        "model_leaf_resolved": bool(getattr(session, "model_leaf_resolved", None)),
        "negated_count": len(negated_vns or ()), "pending_count": len(pending or []),
        "filled_count": len(filled or {}), "elapsed_ms": int((time.monotonic() - _step3_t0) * 1000),
        "turn": getattr(session, "turn", None)})
    return None, visible_attrs, filled, display_filled, pending, constrained_opts, rule_ids, dropped_note
