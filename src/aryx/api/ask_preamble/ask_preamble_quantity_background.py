"""Session-level product-quantity background capture, and the
"quantity mentioned before any quote started" gate — split out of
`_run_cpq_turn_inner`'s pre-STEP-1 preamble (Phase 10/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md —
docs/CPQ_QUANTITY_SLOTFILLING_AND_UI_ISSUES_PLAN_2026_08_11.md). Runs on
EVERY turn, unconditionally, before any other gate — this is what
captures a quantity stated as part of a fresh order on turn 1, not just
a later direct question about it. A plain overwrite, not "first wins":
restating the quantity later means the new number. An implausible number
is silently ignored rather than rejected — this is an inferred
background capture, not an explicit instruction. Logic unchanged from
the original inline block. Every ask_api name below is read through the
module object (not imported by name) since tests patch several of them
by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.quantity.quantity_hint_extraction import extract_quantity_hint
from aryx.cpq.quantity.quantity_patterns import is_valid_product_quantity
from aryx.cpq.quantity.quantity_turn_detection import question_mentions_quantity, quantity_turn_precheck

from aryx.api.ask_core_helpers import _safe_detect_product_mention
from aryx.api.ask_llm.ask_llm_confirm_extract_quantity import _llm_confirm_and_extract_quantity
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.raven_log import raven_log


def _preamble_capture_quantity_background(
    req: "Any", session: Any, route_meta: "Any | None",
) -> int | None:
    """Mutates `session.product_quantity` in place when a quantity is
    found. Returns `_qty_hint` for the caller's later dedicated-quantity
    gate to reuse (avoids re-extracting the same value twice).
    """
    _qty_hint = extract_quantity_hint(req.question)
    _qty_hint_source = "text" if _qty_hint is not None else "none"
    if _qty_hint is None and route_meta is not None and route_meta.quantity is not None:
        _qty_hint = route_meta.quantity
        _qty_hint_source = "route_meta"
    if _qty_hint is not None and is_valid_product_quantity(_qty_hint):
        _qty_bg_precheck = quantity_turn_precheck(req.question, [])
        if not (_qty_bg_precheck and _qty_bg_precheck.get("has_change_verb")):
            session.product_quantity = _qty_hint
            raven_log("DEBUG", "P4", "ask.preamble.quantity_background quantity captured directly", context={
                "selected_option": "set_direct",
                "available_options": ["set_direct", "llm_confirmed", "llm_rejected", "ignore"],
                "reason_code": "NO_CHANGE_VERB", "quantity": _qty_hint, "hint_source": _qty_hint_source,
                "turn": getattr(session, "turn", None)})
        else:
            _qty_bg_confirmed, _qty_bg_value, _ = _llm_confirm_and_extract_quantity(
                req, session, [],
                hiding_rules=[], rec_rules=[], con_rules=[], bml_eval=None, catalog_prefix="",
                fallback_value=_qty_hint, fallback_decimal=None,
            )
            _qty_bg_applied = bool(_qty_bg_confirmed and _qty_bg_value is not None)
            raven_log("DEBUG", "P4", "ask.preamble.quantity_background change-verb quantity checked by LLM",
                      context={
                          "selected_option": "llm_confirmed" if _qty_bg_applied else "llm_rejected",
                          "available_options": ["set_direct", "llm_confirmed", "llm_rejected", "ignore"],
                          "reason_code": "LLM_CONFIRMED" if _qty_bg_applied else "LLM_REJECTED_OR_NO_VALUE",
                          "hint_quantity": _qty_hint, "hint_source": _qty_hint_source,
                          "llm_quantity": _qty_bg_value if isinstance(_qty_bg_value, (int, float)) else None,
                          "turn": getattr(session, "turn", None)})
            if _qty_bg_confirmed and _qty_bg_value is not None:
                session.product_quantity = _qty_bg_value
    elif _qty_hint is not None:
        raven_log("DEBUG", "P4", "ask.preamble.quantity_background implausible quantity ignored", context={
            "selected_option": "ignore",
            "available_options": ["set_direct", "llm_confirmed", "llm_rejected", "ignore"],
            "reason_code": "IMPLAUSIBLE_QUANTITY", "hint_quantity": _qty_hint,
            "hint_source": _qty_hint_source, "turn": getattr(session, "turn", None)})
    return _qty_hint


def _preamble_quantity_no_quote_gate(
    req: "Any", session: Any, reader: Any, qty_hint: int | None,
) -> dict[str, Any] | None:
    """A quantity question/statement before any quote has even started
    (no product selected yet). Returns a response dict when this gate
    fires; None otherwise, in which case the caller continues.
    """
    if not (
        not session.product_name
        and question_mentions_quantity(req.question)
        and qty_hint is None
        and not _safe_detect_product_mention(
            req.question, reader, req.workspace_id)
    ):
        raven_log("DEBUG", "P4", "ask.preamble.quantity_no_quote gate not applicable", context={
            "selected_option": "skip", "available_options": ["no_quote_reply", "skip"],
            "reason_code": "PRODUCT_SELECTED" if getattr(session, "product_name", None)
            else "HAS_QUANTITY_HINT" if qty_hint is not None else "CONDITIONS_NOT_MET",
            "turn": getattr(session, "turn", None)})
        return None
    _qty_pre_anchor = quantity_turn_precheck(req.question, [])
    if _qty_pre_anchor is None:
        raven_log("DEBUG", "P4", "ask.preamble.quantity_no_quote precheck found no quantity turn", context={
            "selected_option": "skip", "available_options": ["no_quote_reply", "skip"],
            "reason_code": "PRECHECK_NONE", "turn": getattr(session, "turn", None)})
        return None
    raven_log("INFO", "P4", "ask.preamble.quantity_no_quote quantity asked before any quote, gate handled turn",
              context={
                  "selected_option": "no_quote_reply", "available_options": ["no_quote_reply", "skip"],
                  "reason_code": "QUANTITY_BEFORE_PRODUCT", "turn": getattr(session, "turn", None),
                  "default_quantity": getattr(session, "product_quantity", None),
                  "question_len": len(getattr(req, "question", "") or "")})
    answer = (
        f"Quantity is not configured yet — no quote has been started, so "
        f"there's nothing to set a quantity on (it defaults to "
        f"**{session.product_quantity}** once you do). What would you "
        f"like to order?"
    )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_product_quantity_no_quote()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
