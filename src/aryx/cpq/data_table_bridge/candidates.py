"""CPQModel candidate resolution -- part of the Data-Table-conflict helper
cluster extracted from ``cpq/engine.py`` (Phase 4 step 1,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Stateless, purely-functional
wrapper over already-external ``data_table_resolver`` calls.
"""

from __future__ import annotations

import logging

from aryx.config import get_settings
from aryx.cpq import model_resolution as _model_resolution
from aryx.cpq.auto_fill_stages import fill_log
from aryx.raven_log import raven_log, would_log
from aryx.cpq.data_table.data_table_resolver import (
    discover_cpq_models_for_base_model as dt_discover_cpq_models_for_base_model,
    resolve_models_by_hierarchy_display as dt_resolve_models_by_display,
    resolve_product_cpq_model_family as dt_resolve_product_cpq_model_family,
    resolve_sibling_models_with_sequence_rows as dt_resolve_sibling_models,
    resolve_punctuated_sequence_models as dt_resolve_punctuated_models,
    resolve_product_cpq_models_from_rows as dt_resolve_product_cpq_models_from_rows,
)
from aryx.cpq.data_table.model_key_map import front_mapped_key as dt_front_mapped_key

logger = logging.getLogger(__name__)

_DEFAULT_CPQ_MODEL_CANDIDATES: tuple[str, ...] = ("APXNEXT", "APXNEXT_BOM")
_TIERS = ["tier1_text_match", "tier2_model_resolution", "tier2_hierarchy_display_match", "tier3_base_model",
          "resolved_model_prepend", "catalog_model_key", "real_models_first", "static_fallback"]


def _log_candidates(tier: str, result: tuple, product_name: str, workspace_id: int | None,
                    base_extra: int = 0) -> None:
    """G3 -- ask.model.candidates (DEBUG) per call; WARN once per turn per result for the static pair."""
    static = tier == "static_fallback"
    ctxd = {
        "selected_option": list(result), "available_options": _TIERS,
        "reason_code": tier.upper() if not static else "NO_TIER_RESULT", "policy_version": "cpq_model_candidates_v1",
        "product_name": product_name, "tier": tier, "static_fallback_used": static,
        "workspace_id": workspace_id, "base_model_extra_count": base_extra}
    if static and fill_log.fallback_static_first_in_turn(result):
        raven_log("WARN", "P3", "ask.model.fallback_static used the fixed APXNEXT pair",
                  error_code="ARYX_ASK_MODEL_FALLBACK_STATIC", context={**ctxd, "first_in_turn": True})
    elif would_log("DEBUG"):
        raven_log("DEBUG", "P4", "ask.model.candidates tier answered", context=ctxd)


def _prepend_resolved_model(
    primary: tuple[str, ...], product_name: str, base_model: str,
) -> tuple[str, ...]:
    """Port of aryxent PR 3: when `cpq_model_scope_lookups_enabled` is on and
    this turn's resolver knows which model the customer wants, make sure its
    cpqModel is a candidate -- prepended if missing, never replacing or
    removing what tiers 1-3 found. Flag off / no bound turn: `primary`
    returned unchanged.
    """
    if not get_settings().cpq_model_scope_lookups_enabled:
        return primary
    try:
        ctx = _model_resolution.get_turn()
        if ctx is None or not ctx.resolution.resolved or ctx.resolution.chosen is None:
            return primary
        resolved = ctx.resolution.chosen.cpq_model
        if resolved in primary:
            return primary
        if ctx.first_time(("prepend_cpq_model", resolved)):  # ~300 calls/turn
            logger.info(
                "cpq: model_scope prepended_cpq_model product_name=%r "
                "base_model=%r was=%r -> (%r, *was)",
                product_name, base_model, primary, resolved,
            )
        return (resolved, *primary)
    except Exception as exc:  # noqa: BLE001 -- never break candidate resolution
        logger.exception("cpq: model_scope candidate prepend failed product_name=%r", product_name)
        raven_log("WARN", "P3", "ask.model.prepend_failed resolved model not prepended to candidates",
                  error_code="ARYX_ASK_MODEL_PREPEND_FAILED",
                  context={"product_name": product_name, "triggering_error": type(exc).__name__,
                           "attempt": 1, "max_attempts": 1, "backoff_ms": 0,
                           "recovery_selected": "tier_candidates_only", "fallback_target": "tier_candidates",
                           "exit_condition": "degraded", "result": "degraded"})
        return primary


def _memo_store(cache: dict | None) -> dict | None:
    """Where a repeated lookup is remembered: the bound turn's memo when a turn is bound (turn-scoped by
    construction, so it can never replay another turn's answer), else the caller's own cache, else nowhere."""
    try:
        ctx = _model_resolution.get_turn()
    except Exception:  # noqa: BLE001 -- memo is an optimisation, never a failure
        ctx = None
    if ctx is not None:
        return ctx.memo
    return cache


def _cpq_model_candidates(
    product_name: str, workspace_id: int | None = None, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None, base_model: str = "",
) -> tuple[str, ...]:
    """Same answer as `_resolve_cpq_model_candidates`, remembered for the rest of the turn.

    ~25 call sites ask this on every pass (ws 1267, 2026-10-07: 25,232 identical resolutions in 10 minutes). The
    result depends only on the arguments and on data/turn state that is fixed for a turn, so one resolution per
    distinct argument set is enough. Without a per-turn dict (no cache, no bound turn) nothing is remembered.
    With no turn bound the caller's `cache` is used, and it MUST then live no longer than one turn (the result reads
    this turn's model resolution in `_prepend_resolved_model`).
    """
    store = _memo_store(cache)
    key = ("_cpq_model_candidates", product_name, workspace_id, catalog_prefix, base_model)
    if store is not None and key in store:
        return store[key]
    result = _resolve_cpq_model_candidates(product_name, workspace_id, catalog_prefix, cache, base_model)
    if store is not None:
        store[key] = result
    return result


def _resolve_cpq_model_candidates(
    product_name: str, workspace_id: int | None = None, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None, base_model: str = "",
) -> tuple[str, ...]:
    """CPQModel code(s) to try for `product_name`, in priority order:
    1. The real, ingested constraint-shaped Data Table rows' own
       productSelectionProduct_all attr/val pairs
       (data_table_resolver.resolve_product_cpq_models_from_rows) --
       catalog-agnostic and fully data-driven, no per-catalog hardcoding.
    2. Otherwise, the ingested CPQModelHierarchy-shaped Data Table's real
       Product -> cpqModelName mapping, when `workspace_id` is available --
       real, catalog-wide reference data, though only family-level, not
       per-product. Both the bare family code and its "_BOM" variant are
       tried, since every real export seen so far ingests both under the
       same family.
    2b. Otherwise, a model whose own hierarchy row (blank Product) is displayed exactly as `product_name` and that has
       sequence rows (data_table_resolver.resolve_models_by_hierarchy_display), e.g. "APX 1500 Enhanced" ->
       APX1500ENH. Logged as its own tier so it can be told apart from a family or sibling match.
    3. The static APXNEXT/APXNEXT_BOM fallback, when none of the above
       applies (no workspace_id, or the product is in no ingested source
       at all) -- unchanged, UNLESS `data_table_candidates_empty_on_no_
       match_enabled` is on (CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T2
       Phase 4), in which case this step logs the data gap and returns an
       empty tuple instead of guessing APX NEXT. Off by default; see that
       setting's own docstring for the full safety rationale and the "not
       yet verified against a real non-APX-NEXT catalog" caveat.

    `base_model`, when supplied, appends every CPQModel code the real
    ingested Data Tables actually use for that EXACT base model (see
    data_table_resolver.discover_cpq_models_for_base_model) AFTER whichever
    of 1-3 above already matched -- never replacing the primary,
    product-derived candidates, only supplementing them. Omitting
    `base_model` (the default) keeps this function's behavior identical to
    before this parameter existed.
    """
    primary = None
    tier = "tier1_text_match"
    if workspace_id is not None:
        from_rows = dt_resolve_product_cpq_models_from_rows(
            product_name, workspace_id, catalog_prefix, cache,
        )
        if from_rows:
            primary = from_rows
    if primary is None and workspace_id is not None:
        family = dt_resolve_product_cpq_model_family(
            product_name, workspace_id, catalog_prefix, cache,
        )
        if family:
            siblings = dt_resolve_sibling_models(product_name, workspace_id, catalog_prefix, cache)
            siblings += dt_resolve_punctuated_models(product_name, workspace_id, catalog_prefix, cache)
            primary = tuple(m for s in siblings for m in (s, f"{s}_BOM")) + (family, f"{family}_BOM")
            tier = "tier2_model_resolution"
    if primary is None and workspace_id is not None:
        by_display = dt_resolve_models_by_display(product_name, workspace_id, catalog_prefix, cache)
        if by_display:        # a model whose own hierarchy row (blank Product) is displayed as the product's name
            primary = tuple(m for s in by_display for m in (s, f"{s}_BOM"))
            tier = "tier2_hierarchy_display_match"
    if primary is None:
        if get_settings().data_table_candidates_empty_on_no_match_enabled:
            logger.warning(
                "cpq: no real CPQModel candidates resolved for "
                "product_name=%r (ws=%s catalog_prefix=%r) -- returning "
                "empty rather than guessing the APX NEXT fallback "
                "(data_table_candidates_empty_on_no_match_enabled)",
                product_name, workspace_id, catalog_prefix,
            )
            primary = ()
            tier = "empty_no_match"
            raven_log("WARN", "P3", "ask.model.candidates_empty no CPQModel candidate and static fallback disabled",
                      error_code="ARYX_ASK_MODEL_CANDIDATES_EMPTY", context={
                          "product_name": product_name, "workspace_id": workspace_id,
                          "reason_code": "NO_MATCH_EMPTY_ON_NO_MATCH", "tier": tier})
        else:
            primary = _DEFAULT_CPQ_MODEL_CANDIDATES
            tier = "static_fallback"
    original = primary
    primary = _prepend_resolved_model(primary, product_name, base_model)
    if primary != original:
        # A turn-resolved cpqModel was put in front: the static pair is no
        # longer what callers try first, so it is not a static fallback.
        tier = "resolved_model_prepend"
    if original != _DEFAULT_CPQ_MODEL_CANDIDATES:
        fronted = dt_front_mapped_key(primary, product_name, workspace_id, catalog_prefix, cache)
        if fronted != primary:
            primary, tier = fronted, "catalog_model_key"
    if not (base_model and workspace_id is not None):
        _log_candidates(tier, primary, product_name, workspace_id)
        return primary
    discovered = dt_discover_cpq_models_for_base_model(
        base_model, workspace_id, catalog_prefix, cache,
    )
    extra = tuple(cm for cm in discovered if cm not in primary)
    if (
        extra and original == _DEFAULT_CPQ_MODEL_CANDIDATES
        and get_settings().cpq_candidates_real_models_first_enabled
    ):
        # Partial port of aryxent PR 3/10: real models discovered for the
        # known base model go BEFORE the generic APXNEXT fallback, so a
        # caller that stops at the first single value no longer answers
        # for APX NEXT. Off by default.
        # The resolved-model prepend (if any) stays in front: resolved model,
        # then real discovered models, then the generic fallback.
        head = primary[: len(primary) - len(original)]
        result = head + extra + original
        _log_candidates("real_models_first", result, product_name, workspace_id, len(extra))
        return result
    _log_candidates(tier, primary + extra, product_name, workspace_id, len(extra))
    return primary + extra if extra else primary
