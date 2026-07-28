"""Session snapshots, undo, and loop-exit counters (post-failure prevention).

- Before any mutating intent: deep-copy CpqSession into session.history[]
  (cap 10; nested history stripped).
- "undo" is a first-class intent restoring the last snapshot.
- Clarify streak per attribute (max 2 → numbered options).
- Unresolved-turn counter (max 5 → offer deterministic guided mode).
"""
from __future__ import annotations

import copy
import logging
import re
from typing import Any

from aryx.cpq.state import ConfigAttr, CpqSession

logger = logging.getLogger(__name__)

HISTORY_CAP = 10
CLARIFY_STREAK_MAX = 2
UNRESOLVED_TURNS_MAX = 5
UTTERANCE_CAP = 20

_UNDO_RE = re.compile(
    r"\b(undo|revert|roll\s*back|go\s+back|previous\s+(?:step|state))\b",
    re.IGNORECASE,
)
_GUIDED_ACCEPT_RE = re.compile(
    r"\b(guided|step\s*by\s*step|deterministic|manual\s+mode)\b",
    re.IGNORECASE,
)

# Snapshot fields that must never nest or explode payload size.
_STRIP_ON_SNAPSHOT = frozenset({"history"})


def detect_undo(question: str) -> bool:
    """True when the user asks to restore the previous session snapshot."""
    return bool(_UNDO_RE.search(question or ""))


def detect_guided_mode_accept(question: str) -> bool:
    """True when the user accepts deterministic guided mode."""
    return bool(_GUIDED_ACCEPT_RE.search(question or ""))


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
    # Preserve the remaining history stack and run_id across restore.
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


def record_utterance(session: CpqSession, question: str) -> None:
    """Keep a short ring of raw user messages for BOM provenance checks."""
    q = (question or "").strip()
    if not q:
        return
    session.recent_utterances.append(q)
    while len(session.recent_utterances) > UTTERANCE_CAP:
        session.recent_utterances.pop(0)


def note_clarify(session: CpqSession, variable_name: str | None) -> int:
    """Increment clarify streak for vn (or global '_'). Return new streak."""
    key = variable_name or "_"
    session.clarify_streak_by_vn[key] = session.clarify_streak_by_vn.get(key, 0) + 1
    session.unresolved_turns += 1
    return session.clarify_streak_by_vn[key]


def clear_clarify(session: CpqSession, variable_name: str | None = None) -> None:
    """Reset streak after a successful resolution."""
    if variable_name:
        session.clarify_streak_by_vn.pop(variable_name, None)
    session.unresolved_turns = 0


def should_force_numbered_options(session: CpqSession, variable_name: str | None) -> bool:
    key = variable_name or "_"
    return session.clarify_streak_by_vn.get(key, 0) >= CLARIFY_STREAK_MAX


def should_offer_guided_mode(session: CpqSession) -> bool:
    return session.unresolved_turns >= UNRESOLVED_TURNS_MAX and not session.guided_mode


def numbered_options_prompt(attr: ConfigAttr) -> str:
    """Present menu options as a 1-based numbered list (loop-exit)."""
    lines = [
        f"I want to lock this in without more back-and-forth. "
        f"Pick a number for **{attr.display_label}**:"
    ]
    for i, opt in enumerate(attr.options[:50], start=1):
        lines.append(f"{i}. {opt.display_name}")
    if not attr.options:
        lines.append("(free text — type the value exactly)")
    return "\n".join(lines)


def guided_mode_offer_message() -> str:
    return (
        "We've hit several turns without a clean resolution. "
        "I can switch to **guided mode** (step-by-step, deterministic questions only) "
        "— say **guided** to enable, or keep going with a clearer answer."
    )


def undo_empty_message() -> str:
    return "There's nothing to undo yet — no prior configuration snapshot is stored."


def undo_success_message(session: CpqSession) -> str:
    n = len(session.filled) + len(session.filled_multi)
    return (
        f"Reverted to the previous configuration snapshot "
        f"({n} field(s) restored). Continue, or say **undo** again."
    )
