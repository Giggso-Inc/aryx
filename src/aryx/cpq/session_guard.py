"""Session snapshots, undo, and loop-exit counters (post-failure prevention).

- Before any mutating intent: deep-copy CpqSession into session.history[]
  (cap 10; nested history stripped).
- "undo" is a first-class intent restoring the last snapshot.
- Clarify streak per attribute (max 2 → numbered options).
- Unresolved-turn counter (max 5 → offer deterministic guided mode).
- Conversational orphan-question invariant.

Intent queue / conservation lives in ``aryx.cpq.intent_queue`` (re-exported
here for call-site stability).

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), this module
is split across three focused files by concern — `session_guard_snapshot.py`
(history/undo), `session_guard_loop.py` (clarify-streak counters and
loop-exit prompts), `session_guard_invariant.py` (orphan-question
guardrail) — all re-imported here. Zero whitebox test patches exist
anywhere against `aryx.cpq.session_guard.*` (confirmed via grep), so the
split was purely mechanical.
"""
from __future__ import annotations

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
from aryx.cpq.session_guard_invariant import (
    answer_is_config_question,
    assert_conversational_invariant,
    enforce_conversational_invariant,
    has_consumable_pending_state,
)
from aryx.cpq.session_guard_loop import (
    CLARIFY_STREAK_MAX,
    UNRESOLVED_TURNS_MAX,
    UTTERANCE_CAP,
    clear_clarify,
    detect_guided_mode_accept,
    guided_mode_offer_message,
    match_clarify_reply_offline,
    note_clarify,
    numbered_attr_pick_prompt,
    numbered_options_prompt,
    record_utterance,
    should_force_numbered_options,
    should_offer_guided_mode,
)
from aryx.cpq.session_guard_snapshot import (
    HISTORY_CAP,
    detect_undo,
    push_snapshot,
    restore_last_snapshot,
    undo_empty_message,
    undo_success_message,
)

__all__ = [
    "CLARIFY_STREAK_MAX",
    "HISTORY_CAP",
    "INTENT_QUEUE_CAP",
    "IntentAuditResult",
    "UNRESOLVED_TURNS_MAX",
    "UTTERANCE_CAP",
    "answer_is_config_question",
    "assert_conversational_invariant",
    "audit_intent_conservation",
    "clear_clarify",
    "clear_queue_vn",
    "detect_guided_mode_accept",
    "detect_undo",
    "drain_intent_queue_into_pending",
    "enforce_conversational_invariant",
    "enqueue_intent_targets",
    "format_dropped_intent_notice",
    "format_queue_overflow_notice",
    "guided_mode_offer_message",
    "has_consumable_pending_state",
    "intent_dropped_count",
    "match_clarify_reply_offline",
    "note_clarify",
    "numbered_attr_pick_prompt",
    "numbered_options_prompt",
    "pop_intent_queue_head",
    "push_snapshot",
    "record_utterance",
    "reset_intent_dropped_count",
    "restore_last_snapshot",
    "should_force_numbered_options",
    "should_offer_guided_mode",
    "undo_empty_message",
    "undo_success_message",
]
