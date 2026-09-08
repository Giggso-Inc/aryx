"""STEP 5 pending-answer scope/constraint setup, split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Recomputes the
constrained option set exactly as it was shown last turn (session.filled
hasn't changed yet), then intersects it with any durable remembered
scope (PROMPT 7, session.pending_scope_candidates) so a typo/mismatch
never widens back out to the full catalog. The in-scope resolve
(LLM-first, deterministic-ladder-second, docs/CPQ_PRODUCT_SCOPE_LLM_
FIRST_PLAN_2026_08_13.md) can itself fully answer the turn (skip/
family_only). Logic unchanged from the original inline block. Every
ask_api name below is read through the module object (not imported by
name) since tests patch several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_scope_reask_responses import _build_scope_family_only_response, _build_scope_skip_response, _resolve_scope_reply


def _step9_scope_and_constraint_setup(
    req: "Any", session: Any, attrs: list, pending_attr: Any, pending_var: str,
    hints: dict, con_rules: list, bml_eval: Any, catalog_prefix: str,
) -> "tuple[dict[str, Any] | None, str | None, list | None, list, bool, str]":
    """Returns (early_response, hint_val_for_attr, pending_constrained,
    scope_cands, scope_for_attr, scope_match_text). `early_response` is
    non-None when the in-scope resolve fully answered this turn (skip or
    family_only); the caller must return it immediately when present.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    logger = _ask_api_module.logger

    vn_flat_pv = pending_var.lower().replace("_", "")
    hint_val_for_attr = next(
        (hv for hk, hv in hints.items()
         if hk.lower().replace("_", "") in vn_flat_pv
         or vn_flat_pv in hk.lower().replace("_", "")),
        None,
    )
    _pending_co: dict[int, list[str]] = {}
    _pc = _cpq_engine.apply_constraint_rules(
        attrs, con_rules, session.filled, bml_eval=bml_eval, filled_multi=session.filled_multi,
    ).get(pending_attr.entity_id)
    if _pc is not None:
        _pending_co[pending_attr.entity_id] = _pc
    _cpq_engine._apply_series_mapping_exclusions(
        attrs, _pending_co, session.filled, req.workspace_id, catalog_prefix,
    )
    pending_constrained = _pending_co.get(pending_attr.entity_id, _pc)

    _scope_cands = list(session.pending_scope_candidates or [])
    _scope_for_attr = (
        bool(_scope_cands)
        and (
            not session.pending_scope_attr_vn
            or session.pending_scope_attr_vn == pending_var
        )
    )
    if _scope_for_attr and pending_constrained is None:
        _scope_ivs: list[str] = []
        for o in pending_attr.options or []:
            if (
                o.item_value in _scope_cands
                or o.display_name in _scope_cands
            ):
                _scope_ivs.append(o.item_value)
        if _scope_ivs:
            pending_constrained = _scope_ivs
    elif _scope_for_attr and pending_constrained is not None:
        _scope_ivs = []
        for o in pending_attr.options or []:
            if o.item_value not in pending_constrained:
                continue
            if (
                o.item_value in _scope_cands
                or o.display_name in _scope_cands
            ):
                _scope_ivs.append(o.item_value)
        if _scope_ivs:
            pending_constrained = _scope_ivs

    _scope_match_text = req.question
    if _scope_for_attr and pending_attr.select_type != "multi":
        _scope_label_early = _cpq_engine.disambiguated_label(pending_attr, attrs)
        _scope_reply = _resolve_scope_reply(
            req.question, _scope_cands, _scope_label_early,
            session, req.workspace_id,
        )
        if _scope_reply == "skip":
            return (
                _build_scope_skip_response(
                    req, session, _scope_cands, _scope_label_early,
                ),
                hint_val_for_attr, pending_constrained, _scope_cands, _scope_for_attr,
                _scope_match_text,
            )
        if _scope_reply == "family_only":
            return (
                _build_scope_family_only_response(
                    req, session, _scope_cands, _scope_label_early,
                ),
                hint_val_for_attr, pending_constrained, _scope_cands, _scope_for_attr,
                _scope_match_text,
            )
        _sres = _scope_reply
        if _sres.matched:
            _scope_match_text = _sres.matched
            logger.info(
                "cpq_scope_match tier=%s attr=%s match=%r run_id=%s",
                _sres.tier, pending_var, _sres.matched,
                session.run_id or "-",
            )

    return None, hint_val_for_attr, pending_constrained, _scope_cands, _scope_for_attr, _scope_match_text
