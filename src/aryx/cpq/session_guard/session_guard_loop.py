"""Clarify-streak counters, loop-exit prompts, and offline clarify-reply matching.

Split out of `cpq/session_guard.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import re

from aryx.cpq.state import ConfigAttr, CpqSession

CLARIFY_STREAK_MAX = 2
UNRESOLVED_TURNS_MAX = 5
UTTERANCE_CAP = 20

_GUIDED_ACCEPT_RE = re.compile(
    r"\b(guided|step\s*by\s*step|deterministic|manual\s+mode)\b",
    re.IGNORECASE,
)


def detect_guided_mode_accept(question: str) -> bool:
    """True when the user accepts deterministic guided mode."""
    return bool(_GUIDED_ACCEPT_RE.search(question or ""))


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
