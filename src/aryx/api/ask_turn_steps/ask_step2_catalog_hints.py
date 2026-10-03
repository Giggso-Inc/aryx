"""Catalog-aware hint extraction and cross-turn negation accumulation for
STEP 2, split out of `_run_cpq_turn_inner` (Phase 10/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Scans
the question for real option text extract_hints()'s fixed 3-concept
pattern list has no coverage for; setdefault so the curated patterns
still win where both mechanisms independently find the same attr.
catalog_prefix scopes every rule/function load to the same ingested
catalog attrs came from. The switch-triggering text's own hints are
merged here — AFTER this turn's own extraction AND after the caller's
switch-redetection check — since merging them earlier once caused
detect_product_mention to spuriously re-fire on this same turn
(live-confirmed regression, 2026-07-26). Logic unchanged from the
original inline block. `_cpq_engine` is read through the ask_api module
object (not imported by name) since at least one test replaces the
whole singleton via `patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.rule_trace import rule_trace
from aryx.raven_log import raven_log, would_log



def _step2_catalog_hints_and_negation(
    req: "Any", session: Any, attrs: list, hints: dict, switch_trigger_question: str,
) -> "tuple[str, set]":
    """Mutates `hints` and `session.negated_vns` in place. Returns
    `(catalog_prefix, negated_vns)` for the rest of the turn to use.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    catalog_prefix = attrs[0].catalog_prefix if attrs else ""
    rule_trace.bind_context(req.workspace_id, catalog_prefix)
    _hint_keys_before = set(hints) if would_log("DEBUG") else set()
    catalog_hints, negated_now = _cpq_engine.extract_catalog_hints(req.question, attrs)
    for vn, iv in catalog_hints.items():
        hints.setdefault(vn, iv)
    _flag_hints = _cpq_engine.extract_flag_hints(
        req.question, attrs, req.workspace_id, catalog_prefix,
    )
    for vn, iv in _flag_hints.items():
        hints.setdefault(vn, iv)
    if would_log("DEBUG"):
        raven_log("DEBUG", "P4", "ask.preamble.catalog_hints extracted from this turn", context={
            "catalog_prefix": catalog_prefix, "attr_count": len(attrs or []),
            "catalog_hint_vns": sorted(catalog_hints), "flag_hint_vns": sorted(_flag_hints),
            "added_hint_vns": sorted(set(hints) - _hint_keys_before),
            "negated_now_vns": sorted(negated_now or ()),
            "has_switch_trigger": bool(switch_trigger_question),
            "turn": getattr(session, "turn", None)})

    if switch_trigger_question:
        _hint_keys_before = set(hints) if would_log("DEBUG") else set()
        for k, v in _cpq_engine.extract_hints(switch_trigger_question).items():
            hints.setdefault(k, v)
        _switch_catalog_hints, _ = _cpq_engine.extract_catalog_hints(
            switch_trigger_question, attrs)
        for vn, iv in _switch_catalog_hints.items():
            hints.setdefault(vn, iv)
        for vn, iv in _cpq_engine.extract_flag_hints(
            switch_trigger_question, attrs, req.workspace_id, catalog_prefix,
        ).items():
            hints.setdefault(vn, iv)
        if would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ask.preamble.catalog_hints merged from switch trigger", context={
                "catalog_prefix": catalog_prefix,
                "switch_trigger_len": len(switch_trigger_question or ""),
                "added_hint_vns": sorted(set(hints) - _hint_keys_before),
                "turn": getattr(session, "turn", None)})

    session.negated_vns = sorted(set(session.negated_vns) | negated_now)
    negated_vns = set(session.negated_vns)
    return catalog_prefix, negated_vns
