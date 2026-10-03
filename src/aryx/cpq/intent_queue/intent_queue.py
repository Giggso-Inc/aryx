"""Multi-target intent queue + no-dropped-intent conservation guardrail.

Keeps session_guard under the style line cap while owning:
- pending_intent_queue enqueue / drain / pop
- audit_intent_conservation (cpq_intent_dropped)
- user-visible overflow / drop notices

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`intent_queue_ops.py` (queue enqueue/pop/drain/clear) and
`intent_queue_notices.py` (user-visible notices), both re-imported here.
Zero whitebox test patches exist anywhere against `aryx.cpq.intent_queue.intent_queue.*`
(confirmed via grep), so the split was purely mechanical.
`intent_dropped_count`/`reset_intent_dropped_count`/
`audit_intent_conservation` stay together here since they share the
module-level `_INTENT_DROPPED_COUNT` counter via `global`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from aryx.cpq.intent_queue.intent_queue_notices import format_dropped_intent_notice, format_queue_overflow_notice
from aryx.cpq.intent_queue.intent_queue_ops import (
    clear_queue_vn,
    drain_intent_queue_into_pending,
    enqueue_intent_targets,
    pop_intent_queue_head,
)
from aryx.cpq.state import INTENT_QUEUE_CAP, CpqSession
from aryx.raven_log import raven_log

# Re-export for `from aryx.cpq.intent_queue.intent_queue import INTENT_QUEUE_CAP`
__all__ = [
    "INTENT_QUEUE_CAP",
    "IntentAuditResult",
    "audit_intent_conservation",
    "clear_queue_vn",
    "drain_intent_queue_into_pending",
    "enqueue_intent_targets",
    "format_dropped_intent_notice",
    "format_queue_overflow_notice",
    "intent_dropped_count",
    "pop_intent_queue_head",
    "reset_intent_dropped_count",
]

logger = logging.getLogger(__name__)

_INTENT_DROPPED_COUNT = 0


def intent_dropped_count() -> int:
    """Return process-local count of intent-conservation violations."""
    return _INTENT_DROPPED_COUNT


def reset_intent_dropped_count() -> None:
    """Test helper — zero the dropped-intent counter."""
    global _INTENT_DROPPED_COUNT
    _INTENT_DROPPED_COUNT = 0


@dataclass
class IntentAuditResult:
    """Result of the intent-conservation check."""

    ok: bool
    detected: list[str] = field(default_factory=list)
    handled: list[str] = field(default_factory=list)
    queued: list[str] = field(default_factory=list)
    clarified: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    message: str = ""


def audit_intent_conservation(
    question: str,
    detected_targets: list[str] | set[str],
    handled_vns: list[str] | set[str],
    session: CpqSession | dict[str, Any] | None,
    *,
    clarified_vns: list[str] | set[str] | None = None,
    run_id: str = "",
    turn: int = 0,
    log: bool = True,
) -> IntentAuditResult:
    """Invariant: every detected target is handled, queued, or clarified.

    Any remainder is a dropped intent — logged as ``cpq_intent_dropped``.
    """
    global _INTENT_DROPPED_COUNT
    detected = {v for v in detected_targets if v}
    handled = {v for v in handled_vns if v}
    clarified = {v for v in (clarified_vns or set()) if v}
    overflow: set[str] = set()
    if isinstance(session, CpqSession):
        queued = set(session.pending_intent_queue or [])
        overflow = set(session.pending_intent_overflow or [])
        rid = run_id or session.run_id or "-"
        turn_n = turn or session.turn or 0
        if session.pending_change_no_value_vn:
            clarified.add(session.pending_change_no_value_vn)
        if session.pending_clarify_vns:
            clarified |= set(session.pending_clarify_vns)
        if session.pending_change_collision_vns:
            clarified |= set(session.pending_change_collision_vns)
    elif isinstance(session, dict):
        queued = set(session.get("pending_intent_queue") or [])
        overflow = set(session.get("pending_intent_overflow") or [])
        legacy = session.get("pending_multi_intent_vn") or ""
        if legacy:
            queued.add(legacy)
        rid = run_id or session.get("run_id") or "-"
        turn_n = turn or int(session.get("turn") or 0)
        if session.get("pending_change_no_value_vn"):
            clarified.add(session["pending_change_no_value_vn"])
        if session.get("pending_clarify_vns"):
            clarified |= set(session["pending_clarify_vns"])
        if session.get("pending_change_collision_vns"):
            clarified |= set(session["pending_change_collision_vns"])
    else:
        queued = set()
        rid = run_id or "-"
        turn_n = turn

    accounted = handled | queued | clarified | overflow
    dropped = sorted(detected - accounted)
    result = IntentAuditResult(
        ok=not dropped,
        detected=sorted(detected),
        handled=sorted(handled),
        queued=sorted(queued),
        clarified=sorted(clarified),
        dropped=dropped,
    )
    if dropped:
        _INTENT_DROPPED_COUNT += 1
        result.message = (
            f"cpq_intent_dropped: run_id={rid} turn={turn_n} "
            f"dropped={dropped} question={question!r}"
        )
        if log:
            logger.error("%s", result.message)
            raven_log(
                "WARN", "P3", "ask.intent.dropped detected target neither handled nor queued",
                error_code="ARYX_ASK_INTENT_DROPPED",
                context={"final_status": "dropped", "result": "dropped",
                         "reason_code": "UNACCOUNTED_TARGET", "turn": turn_n, "run_id": rid,
                         "dropped_fields": dropped[:20], "detected_count": len(detected),
                         "handled_count": len(handled), "queued_count": len(queued)},
            )
    if not dropped:
        raven_log("DEBUG", "P4", "ask.intent.conserved every detected target accounted for", context={
            "result": "ok", "turn": turn_n, "run_id": rid, "detected_count": len(detected),
            "handled_count": len(handled), "queued_count": len(queued),
            "clarified_count": len(clarified), "overflow_count": len(overflow)})
    return result
