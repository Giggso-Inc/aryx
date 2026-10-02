"""Re-deriving country/region-derived attrs and re-validating every
constraint-governed attr against a newly-confirmed country, split out of
`_build_country_change_response` (Phase 3/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) purely to keep the
sibling `ask_build_country_change_response.py` under the line cap. Logic
unchanged from the original inline try/except block. `_cpq_engine` and
`logger` are read through the ask_api MODULE object (not imported by
name) since at least one test replaces the whole singleton via
`patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.raven_log import raven_log


def _rederive_and_revalidate_for_country_change(
    req: "Any", session: Any, new_country: str, reader: Any,
) -> None:
    """Re-derive every country/region-derived attr AND re-validate every
    constraint-governed attr against the new country, ONLY if a quote is
    actually in progress — with no product selected there's no catalog to
    reload and nothing to re-derive/re-validate. Never let a failure here
    break the country-change response itself; the display update the
    caller already applied must always succeed regardless.

    Uses the SAME full hide->recommend->constrain->auto-fill loop
    (evaluate_rules_loop) every other mutating turn in this file already
    uses (e.g. _handle_cascade) instead of a single standalone auto_fill
    call -- live-verified a bare auto_fill call isn't enough: at least one
    real boolean attr in this catalog (a country==Canada flag) is only
    ever set correctly by a script-backed RECOMMENDATION rule evaluated
    via BmlEvaluator, which only runs inside this full loop, not a lone
    auto_fill pass. The loop's own returned `constrained_opts` is then
    checked against every currently-filled attr generically (never
    hardcoding a specific attribute name like "productSelectionProduct_
    all") so any attr a catalog author has constrained by country/region
    -- confirmed live for Product via 3 active ConstraintRules, but not
    assumed to be the only one -- gets cleared and re-asked if the new
    country invalidates its current value.
    """
    from aryx.api import ask_api as _ask_api_module
    if not session.product_name:
        return
    _cpq_engine = _ask_api_module._cpq_engine
    try:
        attrs, _resolved_name = _cpq_engine.load_product_config(
            reader, req.workspace_id, session.product_name,
        )
        if not attrs:
            return
        catalog_prefix = attrs[0].catalog_prefix
        hiding_rules = _cpq_engine.load_hiding_rules(
            req.workspace_id, catalog_prefix, session.product_name)
        rec_rules, con_rules = _cpq_engine.load_recommendation_and_constraint_rules(
            req.workspace_id, catalog_prefix)
        bml_eval = _cpq_engine.build_bml_evaluator(req.workspace_id, catalog_prefix)
        skip_always_ask = _cpq_engine.resolve_always_ask_skips(
            req.workspace_id, catalog_prefix, attrs)
        _visible_attrs, session.filled, session.display_filled, _constrained_opts = (
            _cpq_engine.evaluate_rules_loop(
                attrs, {"country": new_country}, session.filled,
                hiding_rules, rec_rules, con_rules,
                bml_eval=bml_eval, filled_source=session.filled_source,
                filled_multi=session.filled_multi,
                country=new_country, skip_always_ask=skip_always_ask,
                workspace_id=req.workspace_id, catalog_prefix=catalog_prefix,
            )
        )
        for _attr in attrs:
            # select_type=="multi"'s real value lives in filled_multi,
            # never filled -- the docstring above says every currently-
            # filled attr is checked generically, but the scalar-only read
            # below silently always skipped a multi-select (confirmed
            # live 2026-08-21, same root cause as the cascade-dependent
            # gaps just fixed in _handle_cascade/_handle_cascade_multi/the
            # pending-answer lock -- a stale, now-illegal multi-select
            # selection could survive a country change indefinitely).
            if _attr.select_type == "multi":
                _current_multi_vals = session.filled_multi.get(_attr.variable_name)
                if not _current_multi_vals:
                    continue
                _allowed_vals = _constrained_opts.get(_attr.entity_id)
                if _allowed_vals is None:
                    continue
                _kept_vals = [v for v in _current_multi_vals if v in _allowed_vals]
                if _kept_vals != _current_multi_vals:
                    _ask_api_module.logger.info(
                        "cpq_country_change_invalidated_attr: "
                        "turn=%s attr=%s value=%r no longer fully "
                        "valid for country=%r (allowed=%r) — "
                        "clearing invalid selections for re-ask",
                        session.turn, _attr.variable_name,
                        _current_multi_vals, new_country, _allowed_vals,
                    )
                    if _kept_vals:
                        session.filled_multi[_attr.variable_name] = _kept_vals
                        session.display_filled[_attr.variable_name] = ", ".join(
                            next(
                                (o.display_name for o in _attr.options
                                 if o.item_value == v), v,
                            )
                            for v in _kept_vals
                        )
                    else:
                        session.filled_multi.pop(_attr.variable_name, None)
                        session.display_filled.pop(_attr.variable_name, None)
                        session.filled_source.pop(_attr.variable_name, None)
                continue
            _current_val = session.filled.get(_attr.variable_name)
            if not _current_val:
                continue
            _allowed_vals = _constrained_opts.get(_attr.entity_id)
            if _allowed_vals is not None and _current_val not in _allowed_vals:
                _ask_api_module.logger.info(
                    "cpq_country_change_invalidated_attr: "
                    "turn=%s attr=%s value=%r no longer valid "
                    "for country=%r (allowed=%r) — clearing for re-ask",
                    session.turn, _attr.variable_name, _current_val,
                    new_country, _allowed_vals,
                )
                session.filled.pop(_attr.variable_name, None)
                session.display_filled.pop(_attr.variable_name, None)
                session.filled_source.pop(_attr.variable_name, None)
    except Exception:
        _ask_api_module.logger.warning(
            "cpq_country_change_rederive_failed: turn=%s "
            "product=%r new_country=%r — mirror attrs/Product "
            "re-validation skipped, display update still applied",
            session.turn, session.product_name, new_country,
            exc_info=True,
        )
        raven_log(
            "WARN", "P3", "ask.country_rederive.failed country change re-validation skipped",
            error_code="ARYX_ASK_COUNTRY_REDERIVE_FAILED",
            context={"triggering_error": "rederive_exception", "attempt": 1, "max_attempts": 1,
                     "recovery_selected": "skip_revalidation", "fallback_target": "display_update_only",
                     "exit_condition": "exception", "result": "degraded", "turn": session.turn,
                     "product": session.product_name, "new_country": new_country,
                     "run_id": getattr(session, "run_id", "")},
        )
