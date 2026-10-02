"""Committing STEP 3's recomputed state back into the session, logging
the cascade delta, and draining the multi-target intent queue, split
out of `_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). `dropped_note`
distinguishes a value the SESSION already held before this turn (a real
prior answer, now invalidated) from one evaluate_rules_loop's own
internal iteration filled AND discarded within this SAME turn — it is
suppressed from the customer-facing response by explicit product
decision (logged instead so the cascade stays auditable). A
filled_multi value is kept dormant rather than purged just because it
isn't part of THIS turn's visible set — only dropped_multi entries or
catalog-absent variables are actually removed. Logic unchanged from the
original inline block. `logger` is read through the ask_api module
object (not imported by name) since tests patch several ask_api names
by dotted path.
"""

from __future__ import annotations

import time
from typing import Any

from aryx.cpq.session_guard.session_guard import clear_queue_vn, drain_intent_queue_into_pending
from aryx.raven_log import raven_log


def _step10_commit_and_drain(
    session: Any, attrs: list, visible_attrs: list, filled: dict, display_filled: dict,
    pending: list, dropped_multi: dict, prev_filled_snapshot: dict,
    prev_filled_multi_snapshot: dict, pending_var: str | None, step3_t0: float,
) -> "tuple[str, list]":
    """Mutates `session` in place. Returns (dropped_note, pending) — the
    caller's `pending` list may be replaced by intent-queue draining.
    """
    from aryx.api import ask_api as _ask_api_module
    logger = _ask_api_module.logger

    def _dropped_phrase(dvar: str, dvals: list[str]) -> str:
        label = next((a.display_label for a in attrs if a.variable_name == dvar), dvar)
        had_prior_value = dvar in prev_filled_snapshot or bool(prev_filled_multi_snapshot.get(dvar))
        if had_prior_value:
            return (
                f" Removed **{', '.join(dvals)}** from **{label}** "
                f"— no longer valid after this change."
            )
        return f" **{label}** doesn't currently offer **{', '.join(dvals)}** as a valid option."

    dropped_note = "".join(
        _dropped_phrase(dvar, dvals) for dvar, dvals in dropped_multi.items()
    )
    if dropped_note:
        logger.info(
            "cpq_cascade_dropped_note (suppressed from customer response): "
            "%s [run_id=%s]", dropped_note.strip(), session.run_id or "-",
        )
        dropped_note = ""

    session.filled = filled
    session.display_filled = display_filled
    session.pending_variables = [a.variable_name for a in pending]
    session.filled_source = {
        k: v for k, v in session.filled_source.items()
        if k in filled or k in session.filled_multi
    }
    session.filled_multi = {
        k: v for k, v in session.filled_multi.items()
        if k not in dropped_multi and any(a.variable_name == k for a in attrs)
    }
    _changed_vars: list[str] = []
    for var, new_val in filled.items():
        old_val = prev_filled_snapshot.get(var)
        if old_val != new_val:
            _changed_vars.append(var)
            session.cascade_log.append({
                "var": var, "old": old_val, "new": new_val,
                "rule": session.filled_source.get(var, ""), "turn": getattr(session, "turn", None),
            })

    logger.info(
        "cpq_step: step3_rule_eval done run_id=%s elapsed_s=%.3f",
        session.run_id, time.monotonic() - step3_t0,
    )

    clear_queue_vn(session, pending_var)
    _pending_before_drain = len(pending or [])
    pending = drain_intent_queue_into_pending(session, pending, visible_attrs)
    raven_log("DEBUG", "P4", "ask.recompute.commit rule-eval state committed and queue drained", context={
        "selected_option": "drained" if len(pending or []) != _pending_before_drain else "no_queue_change",
        "available_options": ["drained", "no_queue_change"],
        "reason_code": "STEP3_COMMITTED", "pending_field": pending_var,
        "filled_count": len(filled or {}), "changed_fields": _changed_vars[:25],
        "changed_count": len(_changed_vars),
        "dropped_multi_fields": list(dropped_multi or {})[:25],
        "dropped_note_suppressed": bool(dropped_multi),
        "pending_before_drain": _pending_before_drain, "pending_after_drain": len(pending or []),
        "elapsed_ms": int((time.monotonic() - step3_t0) * 1000),
        "turn": getattr(session, "turn", None)})
    return dropped_note, pending
