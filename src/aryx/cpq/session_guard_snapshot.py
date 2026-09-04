"""Session history snapshots and undo.

Split out of `cpq/session_guard.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import copy
import logging
import re

from aryx.cpq.state import CpqSession

logger = logging.getLogger(__name__)

HISTORY_CAP = 10

_UNDO_RE = re.compile(
    r"\b(undo|revert|roll\s*back|go\s+back|previous\s+(?:step|state))\b",
    re.IGNORECASE,
)

# Snapshot fields that must never nest or explode payload size.
_STRIP_ON_SNAPSHOT = frozenset({"history"})


def detect_undo(question: str) -> bool:
    """True when the user asks to restore the previous session snapshot."""
    return bool(_UNDO_RE.search(question or ""))


def push_snapshot(session: CpqSession, reason: str = "mutating") -> None:
    """Deep-copy session state onto session.history before a mutation."""
    raw = session.to_dict()
    for key in _STRIP_ON_SNAPSHOT:
        raw.pop(key, None)
    snap = copy.deepcopy(raw)
    snap["_snapshot_reason"] = reason
    session.history.append(snap)
    while len(session.history) > HISTORY_CAP:
        session.history.pop(0)
    logger.info(
        "cpq_session_guard: snapshot pushed reason=%s history_len=%d run_id=%s",
        reason, len(session.history), session.run_id or "-",
    )


def restore_last_snapshot(session: CpqSession) -> bool:
    """Pop and restore the most recent snapshot. Returns False if empty."""
    if not session.history:
        return False
    snap = session.history.pop()
    snap = dict(snap)
    snap.pop("_snapshot_reason", None)
    remaining = list(session.history)
    run_id = session.run_id
    restored = CpqSession.from_dict(snap)
    for field_name in CpqSession.__dataclass_fields__:
        if field_name in ("history", "run_id"):
            continue
        setattr(session, field_name, getattr(restored, field_name))
    session.history = remaining
    session.run_id = run_id
    logger.info(
        "cpq_session_guard: undo restored history_len=%d run_id=%s",
        len(session.history), session.run_id or "-",
    )
    return True


def undo_empty_message() -> str:
    return "There's nothing to undo yet — no prior configuration snapshot is stored."


def undo_success_message(session: CpqSession) -> str:
    n = len(session.filled) + len(session.filled_multi)
    return (
        f"Reverted to the previous configuration snapshot "
        f"({n} field(s) restored). Continue, or say **undo** again."
    )
