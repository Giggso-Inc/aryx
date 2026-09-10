"""CPQ session-guard (undo/snapshot/loop-exit) package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "CLARIFY_STREAK_MAX": "session_guard_loop",
    "HISTORY_CAP": "session_guard_snapshot",
    "UNRESOLVED_TURNS_MAX": "session_guard_loop",
    "UTTERANCE_CAP": "session_guard_loop",
    "answer_is_config_question": "session_guard_invariant",
    "assert_conversational_invariant": "session_guard_invariant",
    "clear_clarify": "session_guard_loop",
    "detect_guided_mode_accept": "session_guard_loop",
    "detect_undo": "session_guard_snapshot",
    "enforce_conversational_invariant": "session_guard_invariant",
    "guided_mode_offer_message": "session_guard_loop",
    "has_consumable_pending_state": "session_guard_invariant",
    "match_clarify_reply_offline": "session_guard_loop",
    "note_clarify": "session_guard_loop",
    "numbered_attr_pick_prompt": "session_guard_loop",
    "numbered_options_prompt": "session_guard_loop",
    "push_snapshot": "session_guard_snapshot",
    "record_utterance": "session_guard_loop",
    "restore_last_snapshot": "session_guard_snapshot",
    "should_force_numbered_options": "session_guard_loop",
    "should_offer_guided_mode": "session_guard_loop",
    "undo_empty_message": "session_guard_snapshot",
    "undo_success_message": "session_guard_snapshot",
    # Transitively re-exported from cpq/intent_queue/ (a separate cluster);
    # session_guard.py's own module namespace retains these via its import,
    # so point external package-root callers at that shim module directly.
    "INTENT_QUEUE_CAP": "session_guard",
    "IntentAuditResult": "session_guard",
    "audit_intent_conservation": "session_guard",
    "clear_queue_vn": "session_guard",
    "drain_intent_queue_into_pending": "session_guard",
    "enqueue_intent_targets": "session_guard",
    "format_dropped_intent_notice": "session_guard",
    "format_queue_overflow_notice": "session_guard",
    "intent_dropped_count": "session_guard",
    "pop_intent_queue_head": "session_guard",
    "reset_intent_dropped_count": "session_guard",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.session_guard.{mod_name}")
    return getattr(mod, name)
