"""Multi-target intent queue + no-dropped-intent conservation guardrail.

Keeps session_guard under the style line cap while owning:
- pending_intent_queue enqueue / drain / pop
- audit_intent_conservation (cpq_intent_dropped)
- user-visible overflow / drop notices
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from aryx.cpq.state import INTENT_QUEUE_CAP, CpqSession

# Re-export for `from aryx.cpq.intent_queue import INTENT_QUEUE_CAP`
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


def enqueue_intent_targets(
    session: CpqSession,
    vns: list[str],
    *,
    exclude: set[str] | None = None,
    cap: int = INTENT_QUEUE_CAP,
) -> list[str]:
    """Append variable_names to session.pending_intent_queue (deduped, FIFO).

    Returns variable_names that did not fit under ``cap`` (overflow).
    """
    skip = set(exclude or set())
    overflow: list[str] = []
    for vn in vns:
        name = (vn or "").strip()
        if not name or name in skip:
            continue
        if name in session.pending_intent_queue:
            continue
        if len(session.pending_intent_queue) >= cap:
            overflow.append(name)
            continue
        session.pending_intent_queue.append(name)
    if overflow:
        seen = set(session.pending_intent_overflow)
        for vn in overflow:
            if vn not in seen:
                session.pending_intent_overflow.append(vn)
                seen.add(vn)
    return overflow


def pop_intent_queue_head(session: CpqSession) -> str | None:
    """Pop and return the next queued variable_name, or None if empty."""
    if not session.pending_intent_queue:
        return None
    return session.pending_intent_queue.pop(0)


def drain_intent_queue_into_pending(
    session: CpqSession,
    pending: list[Any],
    attrs: list[Any],
) -> list[Any]:
    """Force the queue head to the front of ``pending`` (outranks catalog order).

    Does not pop the queue — head stays until cleared after apply.
    """
    if not session.pending_intent_queue:
        return pending
    head = session.pending_intent_queue[0]
    by_vn = {getattr(a, "variable_name", ""): a for a in attrs}
    head_attr = by_vn.get(head)
    if head_attr is None:
        return pending
    rest = [a for a in pending if getattr(a, "variable_name", "") != head]
    reordered = [head_attr] + rest
    session.pending_variables = [a.variable_name for a in reordered]
    return reordered


def clear_queue_vn(session: CpqSession, variable_name: str | None) -> None:
    """Remove a variable_name from the intent queue after successful apply."""
    if not variable_name:
        return
    session.pending_intent_queue = [
        v for v in session.pending_intent_queue if v != variable_name
    ]


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
    return result


def format_dropped_intent_notice(
    dropped_vns: list[str],
    attrs: list[Any] | None = None,
) -> str:
    """User-visible line for dropped intents (never fail the turn silently)."""
    if not dropped_vns:
        return ""
    by_vn = {
        getattr(a, "variable_name", ""): (
            getattr(a, "display_label", "") or getattr(a, "variable_name", "")
        )
        for a in (attrs or [])
    }
    labels = [by_vn.get(v) or v for v in dropped_vns]
    joined = ", ".join(f"**{lbl}**" for lbl in labels)
    return f"⚠️ I couldn't process: {joined} — please re-ask."


def format_queue_overflow_notice(
    overflow_vns: list[str],
    attrs: list[Any] | None = None,
) -> str:
    """User-visible line when intent queue hits the cap."""
    if not overflow_vns:
        return ""
    by_vn = {
        getattr(a, "variable_name", ""): (
            getattr(a, "display_label", "") or getattr(a, "variable_name", "")
        )
        for a in (attrs or [])
    }
    labels = [by_vn.get(v) or v for v in overflow_vns]
    joined = ", ".join(f"**{lbl}**" for lbl in labels)
    return (
        f"⚠️ I can only track {INTENT_QUEUE_CAP} additional change targets at "
        f"once — please re-ask about: {joined}."
    )
