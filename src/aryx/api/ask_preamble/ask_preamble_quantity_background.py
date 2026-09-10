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


def _preamble_capture_quantity_background(
    req: "Any", session: Any, route_meta: "Any | None",
) -> int | None:
    """Mutates `session.product_quantity` in place when a quantity is
    found. Returns `_qty_hint` for the caller's later dedicated-quantity
    gate to reuse (avoids re-extracting the same value twice).
    """
    _qty_hint = extract_quantity_hint(req.question)
    if _qty_hint is None and route_meta is not None and route_meta.quantity is not None:
        _qty_hint = route_meta.quantity
    if _qty_hint is not None and is_valid_product_quantity(_qty_hint):
        _qty_bg_precheck = quantity_turn_precheck(req.question, [])
        if not (_qty_bg_precheck and _qty_bg_precheck.get("has_change_verb")):
            session.product_quantity = _qty_hint
        else:
            _qty_bg_confirmed, _qty_bg_value, _ = _llm_confirm_and_extract_quantity(
                req, session, [],
                hiding_rules=[], rec_rules=[], con_rules=[], bml_eval=None, catalog_prefix="",
                fallback_value=_qty_hint, fallback_decimal=None,
            )
            if _qty_bg_confirmed and _qty_bg_value is not None:
                session.product_quantity = _qty_bg_value
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
        return None
    _qty_pre_anchor = quantity_turn_precheck(req.question, [])
    if _qty_pre_anchor is None:
        return None
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
