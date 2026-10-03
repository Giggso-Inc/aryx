"""Orchestrator for the pre-STEP-1 preamble of `_run_cpq_turn_inner`
(Phase 10/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md) — session init, first-class UNDO, the show-summary/
guided-mode shortcuts, quantity background capture, the dedicated
quantity gate, the country-change command, and NL-hint extraction with
country resolution. Each sub-stage lives in a sibling
`ask_preamble_*.py` file purely to keep this orchestrator under the
line cap; each returns None to mean "not this stage, keep going" except
the session-init stage, which always returns state the rest of the
preamble needs regardless. Logic and stage order unchanged from the
original inline block.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_preamble.ask_preamble_country_change import _preamble_country_change_gate
from aryx.api.ask_preamble.ask_preamble_hints_and_country import _preamble_extract_hints_and_resolve_country
from aryx.api.ask_preamble.ask_preamble_quantity_background import (
    _preamble_capture_quantity_background,
    _preamble_quantity_no_quote_gate,
)
from aryx.api.ask_preamble.ask_preamble_quantity_gate import _preamble_dedicated_quantity_gate
from aryx.raven_log import raven_log
from aryx.api.ask_preamble.ask_preamble_session_and_shortcuts import (
    _preamble_init_session,
    _preamble_shortcut_gates,
    _preamble_undo_gate,
)


def _preamble_run(
    req: "Any", reader: Any, route_meta: "Any | None",
) -> "tuple[dict[str, Any] | None, Any, dict, bool, str]":
    """Returns (early_response, session, hints, country_llm_call_failed,
    incoming_pending_anchor). `early_response` is non-None when this
    turn is fully handled by one of the preamble gates; the caller must
    return it immediately when present, in which case `hints` is `{}`.
    """
    session, _incoming_pending_anchor = _preamble_init_session(req, reader)

    _undo_response = _preamble_undo_gate(req, session, reader)
    if _undo_response is not None:
        return _undo_response, session, {}, False, _incoming_pending_anchor

    _shortcut_response = _preamble_shortcut_gates(req, session, reader)
    if _shortcut_response is not None:
        return _shortcut_response, session, {}, False, _incoming_pending_anchor

    _qty_hint = _preamble_capture_quantity_background(req, session, route_meta)

    _no_quote_response = _preamble_quantity_no_quote_gate(req, session, reader, _qty_hint)
    raven_log("DEBUG", "P4", "ask.preamble.gate quantity-no-quote gate", context={
        "gate": "quantity_no_quote", "handled_turn": _no_quote_response is not None,
        "quantity_hint_found": bool(_qty_hint), "turn": getattr(session, "turn", None)})
    if _no_quote_response is not None:
        return _no_quote_response, session, {}, False, _incoming_pending_anchor

    _qty_gate_response = _preamble_dedicated_quantity_gate(req, session, reader)
    raven_log("DEBUG", "P4", "ask.preamble.gate dedicated quantity gate", context={
        "gate": "dedicated_quantity", "handled_turn": _qty_gate_response is not None,
        "turn": getattr(session, "turn", None)})
    if _qty_gate_response is not None:
        return _qty_gate_response, session, {}, False, _incoming_pending_anchor

    _country_change_response = _preamble_country_change_gate(req, session, reader)
    raven_log("DEBUG", "P4", "ask.preamble.gate country change gate", context={
        "gate": "country_change", "handled_turn": _country_change_response is not None,
        "turn": getattr(session, "turn", None)})
    if _country_change_response is not None:
        return _country_change_response, session, {}, False, _incoming_pending_anchor

    hints, _country_llm_call_failed = _preamble_extract_hints_and_resolve_country(
        req, session, route_meta,
    )

    return None, session, hints, _country_llm_call_failed, _incoming_pending_anchor
