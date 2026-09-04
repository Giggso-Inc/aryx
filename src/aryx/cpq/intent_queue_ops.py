"""Pending-intent queue mechanics: enqueue/pop/drain/clear.

Split out of `cpq/intent_queue.py` (Raven Style Compliance Plan, Phase
2b, 2026-09-03). Zero test patches against this module — confirmed via
grep.
"""
from __future__ import annotations

from typing import Any

from aryx.cpq.state import INTENT_QUEUE_CAP, CpqSession


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
