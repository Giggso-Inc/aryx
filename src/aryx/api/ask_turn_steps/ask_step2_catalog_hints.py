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

import logging
from typing import Any

from aryx.config import get_settings
from aryx.cpq.rule_trace import rule_trace
from aryx.raven_log import raven_log, would_log

logger = logging.getLogger(__name__)


def _model_discriminators(req: "Any", session: Any, catalog_prefix: str) -> "dict[str, frozenset[str]] | None":
    """The attributes (and values) the anchored product's model separates its base models by, or None.

    Base model narrowing (flag): a typed "700/800 MHz" or "Limited Keypad" is an option of several attributes, so the
    never-guess rule drops it; with these the phrase is hinted for the one owner the model's own rows use. Any
    failure leaves hint extraction exactly as it was."""
    try:
        if not get_settings().cpq_base_model_narrowing_enabled:
            return None
        from aryx.cpq.base_model_narrowing import discriminator_values  # noqa: PLC0415 -- flag-gated
        from aryx.cpq.catalog_profile import PRODUCT_LITERAL  # noqa: PLC0415

        product = (getattr(session, "filled", {}) or {}).get(PRODUCT_LITERAL) or getattr(session, "product_name", "")
        return discriminator_values(product, req.workspace_id, catalog_prefix) or None
    except Exception:  # noqa: BLE001 -- never affects hint extraction
        logger.debug("cpq: model discriminators for hints failed", exc_info=True)
        return None



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
    discriminators = _model_discriminators(req, session, catalog_prefix)
    # Flag off (or nothing to separate): the call is exactly the two-argument call it always was.
    catalog_hints, negated_now = _cpq_engine.extract_catalog_hints(
        req.question, attrs, *((discriminators,) if discriminators else ()))
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

    _merge_anchor_hints(req, session, attrs, hints, catalog_prefix, negated_now)

    session.negated_vns = sorted(set(session.negated_vns) | negated_now)
    negated_vns = set(session.negated_vns)
    return catalog_prefix, negated_vns


def _merge_anchor_hints(
    req: "Any", session: Any, attrs: list, hints: dict, catalog_prefix: str,
    negated_now: set,
) -> None:
    """Also read option text from the earlier message that named the product.

    The country gate answers turn 1 ("I want a quote for APX 900") before
    this step runs, and turn 2 ("United States") scans only its own text,
    so an option named while anchoring the product was never hinted (ws
    1267, 2026-10-07: Product was asked with ~300 options). Lowest priority
    (setdefault, after this turn and the switch trigger); positive hints
    only, never negations; an attr already answered is never overwritten
    (auto_fill tier0_already_filled runs before the hint tier). A completed
    product switch clears product_anchor_question, so an old product's
    message is never re-read.

    `negated_now` is this turn's own negations (not yet folded into
    session.negated_vns -- that happens in the caller, after this call
    returns) -- a variable rejected THIS turn ("no, not the APX 900") or
    any earlier turn (session.negated_vns) must never be re-hinted from
    the anchor, or tier1_hint_match (which has no negation awareness of
    its own -- only tier 5 does) can fill a value the customer just
    rejected. PR #cpq-catalog-hint-exact-code-tiebreak review, Medium
    finding 1 -- confirmed live: without this check, re-hinting fired on
    every later turn too, not just the one where the negation was said.

    Skips the rescan entirely once the product selector is already
    filled (review Medium finding 2): extract_catalog_hints does a full
    scan of every visible attr's options against the anchor text every
    turn, with no caching -- on a large catalog (ws 1267: ~3.2k attrs,
    ~25k options) that is real, repeated work for a result that can only
    ever change the one variable_name this function exists to backfill,
    and that variable_name's value never changes once filled.
    """
    from aryx.api import ask_api as _ask_api_module
    from aryx.cpq.catalog_profile import PRODUCT_LITERAL
    if PRODUCT_LITERAL in getattr(session, "filled", {}):
        return
    anchor = (getattr(session, "product_anchor_question", "") or "").strip()
    if not anchor or anchor == (req.question or "").strip():
        return
    skip_vns = negated_now | set(session.negated_vns)
    _keys_before = set(hints)
    anchor_hints, _ = _ask_api_module._cpq_engine.extract_catalog_hints(anchor, attrs)
    for vn, iv in anchor_hints.items():
        if vn in skip_vns:
            continue
        hints.setdefault(vn, iv)
    raven_log("DEBUG", "P4", "ask.preamble.catalog_hints merged from product anchor", context={
        "selected_option": "merged" if set(hints) - _keys_before else "nothing_new",
        "available_options": ["merged", "nothing_new"], "reason_code": "ANCHOR_MESSAGE_RESCAN",
        "catalog_prefix": catalog_prefix, "anchor_len": len(anchor),
        "added_hint_vns": sorted(set(hints) - _keys_before),
        "skipped_negated_vns": sorted(skip_vns & set(anchor_hints)),
        "turn": getattr(session, "turn", None)})
