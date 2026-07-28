"""Session snapshots, undo, and loop-exit counters (post-failure prevention).

- Before any mutating intent: deep-copy CpqSession into session.history[]
  (cap 10; nested history stripped).
- "undo" is a first-class intent restoring the last snapshot.
- Clarify streak per attribute (max 2 → numbered options).
- Unresolved-turn counter (max 5 → offer deterministic guided mode).
- Conversational orphan-question invariant.

Intent queue / conservation lives in ``aryx.cpq.intent_queue`` (re-exported
here for call-site stability).
"""
from __future__ import annotations

import copy
import logging
import re
from typing import Any

from aryx.cpq.intent_queue import (  # noqa: F401 — re-export public API
    INTENT_QUEUE_CAP,
    IntentAuditResult,
    audit_intent_conservation,
    clear_queue_vn,
    drain_intent_queue_into_pending,
    enqueue_intent_targets,
    format_dropped_intent_notice,
    format_queue_overflow_notice,
    intent_dropped_count,
    pop_intent_queue_head,
    reset_intent_dropped_count,
)
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


# ── Conversational invariant (orphan-question guardrail) ─────────────────────

_CONFIG_QUESTION_RE = re.compile(
    r"(?is)"
    r"(?:"
    r"which\s+(?:value|attribute|field|one|product|country|hardware|"
    r"option|service|catalog|model)\b"
    r"|what\s+(?:value|would you like|is the|are the options)\b"
    r"|did you mean\b"
    r"|which one did you mean\b"
    r"|reply with (?:the )?(?:name|number|value)\b"
    r"|pick a number\b"
    r"|please\s+(?:name|pick|choose|say|provide|confirm|select)\b"
    r"|destination country\b.*\?"
    r"|switch to\b.*\?"
    r"|discard the current configuration\b"
    r")",
)


def answer_is_config_question(answer: str) -> bool:
    """True when the answer is soliciting a config/attribute/anchor reply."""
    if not answer or "?" not in answer:
        return False
    tail = answer.strip()[-600:]
    if "?" not in tail:
        return False
    return bool(_CONFIG_QUESTION_RE.search(tail))


def has_consumable_pending_state(session_data: dict[str, Any] | None) -> bool:
    """True when session_data has pending state that can absorb the next reply."""
    if not session_data:
        return False
    if session_data.get("pending_variables"):
        return True
    if session_data.get("pending_anchor"):
        return True
    if session_data.get("pending_change_collision_vns"):
        return True
    if session_data.get("pending_label_collision_vns"):
        return True
    if session_data.get("pending_change_no_value_vn"):
        return True
    if session_data.get("pending_clarify_vns"):
        return True
    if session_data.get("pending_switch_product") or session_data.get(
        "pending_switch_question",
    ):
        return True
    if session_data.get("pending_switch_candidates"):
        return True
    if session_data.get("pending_model_leaf_candidates"):
        return True
    if session_data.get("pending_intent_queue"):
        return True
    if session_data.get("pending_multi_intent_vn"):
        return True
    return False


def assert_conversational_invariant(
    answer: str,
    session_data: dict[str, Any] | None,
    *,
    run_id: str = "",
    log: bool = True,
) -> list[str]:
    """Post-turn guardrail: config-seeking questions need consumable pending."""
    violations: list[str] = []
    if not answer_is_config_question(answer):
        return violations
    if has_consumable_pending_state(session_data):
        return violations
    rid = run_id or (session_data or {}).get("run_id") or "-"
    msg = (
        f"cpq_orphan_question run_id={rid}: answer asks a config question "
        f"but session has no consumable pending state "
        f"(pending_variables/anchor/collision/clarify/switch/no_value/…)"
    )
    violations.append(msg)
    if log:
        logger.warning("%s | answer_tail=%r", msg, (answer or "")[-180:])
    return violations


def enforce_conversational_invariant(result: dict[str, Any]) -> dict[str, Any]:
    """Attach invariant check onto a CPQ response dict."""
    if not isinstance(result, dict):
        return result
    answer = result.get("answer") or ""
    session_data = result.get("session_data") or {}
    rid = ""
    if isinstance(session_data, dict):
        rid = str(session_data.get("run_id") or "")
    violations = assert_conversational_invariant(
        answer, session_data if isinstance(session_data, dict) else None,
        run_id=rid, log=True,
    )
    if violations:
        result["_cpq_invariant_violations"] = list(violations)
    else:
        result.pop("_cpq_invariant_violations", None)
    return result


def match_clarify_reply_offline(
    reply: str,
    candidates: list[tuple[str, str]],
) -> str | None:
    """Deterministic clarify-reply match for offline multi-turn regression."""
    r = (reply or "").strip()
    if not r or not candidates:
        return None
    r_lower = r.lower().strip(" .,:;!?\"'")
    by_vn = {vn: label for vn, label in candidates}

    if r in by_vn:
        return r
    for vn in by_vn:
        if vn.lower() == r_lower:
            return vn
    for vn, label in candidates:
        if (label or "").lower() == r_lower:
            return vn
    if r.isdigit():
        idx = int(r) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx][0]
    hits: list[str] = []
    for vn, label in candidates:
        label_l = (label or "").lower()
        vn_flat = vn.lower().replace("_", " ")
        if (
            r_lower in label_l
            or label_l in r_lower
            or r_lower in vn_flat
            or vn_flat in r_lower
        ):
            hits.append(vn)
    if len(hits) == 1:
        return hits[0]
    return None


def numbered_attr_pick_prompt(
    candidates: list[tuple[str, str]],
) -> str:
    """Numbered attribute pick list (loop-exit for pending_clarify misses)."""
    lines = [
        "Which attribute did you mean? Reply with the name or the number:",
    ]
    for i, (vn, label) in enumerate(candidates, start=1):
        lines.append(f"{i}. **{label or vn}** (`{vn}`)")
    return "\n".join(lines)
