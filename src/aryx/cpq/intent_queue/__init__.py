"""CPQ intent-queue (conservation/overflow) package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "IntentAuditResult": "intent_queue",
    "audit_intent_conservation": "intent_queue",
    "clear_queue_vn": "intent_queue_ops",
    "drain_intent_queue_into_pending": "intent_queue_ops",
    "enqueue_intent_targets": "intent_queue_ops",
    "format_dropped_intent_notice": "intent_queue_notices",
    "format_queue_overflow_notice": "intent_queue_notices",
    "intent_dropped_count": "intent_queue",
    "pop_intent_queue_head": "intent_queue_ops",
    "reset_intent_dropped_count": "intent_queue",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.intent_queue.{mod_name}")
    return getattr(mod, name)
