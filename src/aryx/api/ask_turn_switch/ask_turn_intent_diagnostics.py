"""Read-only, never-affects-the-turn intent diagnostics logged once
STEP 2 has resolved the product's catalog, split out of `_run_cpq_turn_
inner` (Phase 10/11-phase ask_api decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original
inline block. `_cpq_engine`, `logger`, `get_settings`, and
`_shadow_classify_cpq_turn` are read through the ask_api MODULE object
(not imported by name) since ask_api tests patch several of its own
module-level names by dotted path, and `_shadow_classify_cpq_turn` is
not yet split out of ask_api.py.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_shadow_classify_and_confirm_intent import _shadow_classify_cpq_turn
from aryx.raven_log import raven_log


def _log_turn_intent_diagnostics(req: "Any", session: Any, attrs: list) -> None:
    """Read-only intent-count diagnostic (docs/CPQ_LLM_INTENT_FIRST_
    PLAN.md Fix 4, incremental first step) — measures how many distinct
    intents this message actually contains against real traffic, WITHOUT
    changing any routing behavior. Never allowed to affect the turn:
    wrapped so a failure here can't break anything real.

    Also runs the Phase 1 shadow-mode universal-intent diagnostic (docs/
    CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md) — same read-only, never-
    affects-the-turn guarantee. Logs its own classification for later
    comparison against the real deterministic outcome (logged by run_ask
    after this function returns) via matching run_id — never touches
    routing here. Gated on cpq_shadow_intent_enabled (default off):
    live-confirmed this unconditional LLM call took the CPQ/BML test
    suite from ~10s to ~128s with zero behavioral change — a real
    test-speed/CI-cost regression, separate from the "not a concern in
    production" stance.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    try:
        _intent_hits = _cpq_engine.count_turn_intents(
            req.question, attrs, session.filled, session.filled_multi,
        )
        raven_log("DEBUG", "P4", "ask.intent.count turn intents counted (diagnostic only)", context={
            "selected_option": "multi_intent" if len(_intent_hits) >= 2
            else "single_intent" if _intent_hits else "no_intent",
            "available_options": ["multi_intent", "single_intent", "no_intent"],
            "reason_code": "INTENT_COUNT_DIAGNOSTIC", "intent_count": len(_intent_hits),
            "intent_labels": list(_intent_hits), "turn": getattr(session, "turn", None),
            "question_len": len(getattr(req, "question", "") or "")})
        if len(_intent_hits) >= 2:
            _ask_api_module.logger.info(
                "cpq_intent_count: message %r matched %d distinct intents: %s "
                "-- only the first will actually be addressed today",
                req.question, len(_intent_hits), _intent_hits,
            )
        elif _intent_hits:
            _ask_api_module.logger.debug(
                "cpq_intent_count: message %r matched: %s", req.question, _intent_hits,
            )
    except Exception as exc:  # noqa: BLE001 — diagnostic only, must never break the turn
        _ask_api_module.logger.debug("cpq_intent_count: diagnostic failed", exc_info=True)
        raven_log("WARN", "P3", "ask.intent.count_failed intent-count diagnostic failed, turn continues",
                  error_code="ARYX_ASK_INTENT_COUNT_FAILED", context={
                      "triggering_error": type(exc).__name__, "attempt": 1, "max_attempts": 1,
                      "backoff_ms": 0, "recovery_selected": "skip_diagnostic",
                      "fallback_target": "continue_turn", "exit_condition": "exception",
                      "result": "diagnostic_skipped", "turn": getattr(session, "turn", None)})

    _shadow_enabled = _ask_api_module.get_settings().cpq_shadow_intent_enabled
    raven_log("DEBUG", "P4", "ask.intent.shadow_gate shadow intent classifier gate checked", context={
        "selected_option": "shadow_classify" if _shadow_enabled else "skip",
        "available_options": ["shadow_classify", "skip"],
        "reason_code": "SHADOW_INTENT_ENABLED" if _shadow_enabled else "SHADOW_INTENT_DISABLED",
        "turn": getattr(session, "turn", None)})
    if _shadow_enabled:
        _shadow_classify_cpq_turn(req, session, attrs)
