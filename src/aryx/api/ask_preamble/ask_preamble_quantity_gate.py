"""The dedicated quantity question/change gate, split out of
`_run_cpq_turn_inner`'s pre-STEP-1 preamble (Phase 10/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Resolved
from the session-level value first per the plan's step 3 resolution
order, short-circuiting the catalog-attribute pipeline entirely unless
the message clearly names (or, via disambiguation, picks) a real
competing catalog quantity attribute. Only considered once a product is
selected. Blanket LLM-as-final-verdict checkpoint for a CHANGE attempt
(never a bare question) — reject-on-failure: if the gateway disagrees
or fails, this whole gate is treated as not applicable, falling through
to normal hint/attribute processing. Logic unchanged from the original
inline block. Every ask_api name below is read through the module
object (not imported by name) since tests patch several of them by
dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.quantity_turn_detection import question_mentions_quantity, quantity_turn_precheck

from aryx.api.ask_preamble.ask_preamble_quantity_target_resolve import _preamble_resolve_quantity_target

from aryx.api.ask_response_building.ask_build_product_quantity_response import _build_product_quantity_change_response
from aryx.api.ask_llm.ask_llm_confirm_extract_quantity import _llm_confirm_and_extract_quantity
from aryx.api.ask_llm.ask_llm_extract_quantity_and_country_reply import _llm_extract_quantity
from aryx.api import ask_core_helpers as _ask_core_helpers_module


def _preamble_dedicated_quantity_gate(
    req: "Any", session: Any, reader: Any,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn was fully handled by the
    dedicated quantity gate; None otherwise, in which case the caller
    continues with the normal hint/attribute pipeline (possibly with
    `_qty_target` naming a specific real catalog attribute for it to
    resolve).
    """
    from aryx.api import ask_api as _ask_api_module
    if not (session.product_name and question_mentions_quantity(req.question)):
        return None
    _cpq_engine = _ask_api_module._cpq_engine
    logger = _ask_api_module.logger

    try:
        _qty_attrs, _ = _cpq_engine.load_product_config(
            reader, req.workspace_id, session.product_name,
        )
    except Exception as exc:  # noqa: BLE001 — never crash a turn on this gate
        logger.debug("cpq quantity gate: load_product_config failed: %r", exc)
        _qty_attrs = []
    _qty_pre = quantity_turn_precheck(req.question, _qty_attrs)
    if _qty_pre is None:
        return None

    if (
        _qty_pre["has_change_verb"]
        and _qty_pre["value"] is None
        and _qty_pre.get("decimal_value") is None
    ):
        _qty_llm_value = _llm_extract_quantity(req.question, req.workspace_id)
        if _qty_llm_value is not None:
            _qty_pre["value"] = _qty_llm_value
            _qty_pre["is_change"] = True

    _qty_target, _qty_candidates = _preamble_resolve_quantity_target(req, session, _qty_pre)

    if _qty_target == "product":
        if not _qty_pre["is_change"]:
            _qty_confirmed, _qty_value, _qty_decimal = True, None, None
        else:
            _qty_confirmed, _qty_value, _qty_decimal = _llm_confirm_and_extract_quantity(
                req, session, _qty_attrs,
                hiding_rules=[], rec_rules=[], con_rules=[], bml_eval=None,
                catalog_prefix=(_qty_attrs[0].catalog_prefix if _qty_attrs else ""),
                fallback_value=_qty_pre["value"],
                fallback_decimal=_qty_pre.get("decimal_value"),
            )
        if _qty_confirmed:
            return _build_product_quantity_change_response(
                req, session, reader,
                value=_qty_value if _qty_pre["is_change"] else None,
                decimal_value=(
                    _qty_decimal
                    if _qty_pre["is_change"] else None
                ),
            )
        # else: rejected -- fall through to normal hint/attribute
        # processing below, exactly as if this gate never fired.
        return None

    if _qty_target is None:
        _qty_options = ", ".join(
            f"**{a.display_label}**" for a in _qty_candidates
        )
        answer = (
            f"Are you asking about the overall **product quantity** "
            f"(currently {session.product_quantity}), or the quantity "
            f"for a specific item like {_qty_options}?"
        )
        _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [],
            "tools_called": ["cpq_quantity_disambiguation()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }
    # _qty_target names a specific real catalog attribute — fall through
    # to the normal pipeline below, which resolves it via the existing
    # apply_answer/cascade machinery exactly like any other attribute;
    # this gate's job (deciding WHICH target) is done.
    return None
