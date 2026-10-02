"""CPQModel candidate resolution -- part of the Data-Table-conflict helper
cluster extracted from ``cpq/engine.py`` (Phase 4 step 1,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Stateless, purely-functional
wrapper over already-external ``data_table_resolver`` calls.
"""

from __future__ import annotations

import logging

from aryx.config import get_settings
from aryx.cpq.auto_fill_stages import fill_log
from aryx.raven_log import raven_log, would_log
from aryx.cpq.data_table.data_table_resolver import (
    discover_cpq_models_for_base_model as dt_discover_cpq_models_for_base_model,
    resolve_product_cpq_model_family as dt_resolve_product_cpq_model_family,
    resolve_product_cpq_models_from_rows as dt_resolve_product_cpq_models_from_rows,
)

logger = logging.getLogger(__name__)

_DEFAULT_CPQ_MODEL_CANDIDATES: tuple[str, ...] = ("APXNEXT", "APXNEXT_BOM")
_TIERS = ["tier1_text_match", "tier2_model_resolution", "tier3_base_model", "static_fallback"]


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


def _cpq_model_candidates(
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
            primary = (family, f"{family}_BOM")
            tier = "tier2_model_resolution"
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
    if not (base_model and workspace_id is not None):
        _log_candidates(tier, primary, product_name, workspace_id)
        return primary
    discovered = dt_discover_cpq_models_for_base_model(
        base_model, workspace_id, catalog_prefix, cache,
    )
    extra = tuple(cm for cm in discovered if cm not in primary)
    _log_candidates(tier, primary + extra, product_name, workspace_id, len(extra))
    return primary + extra if extra else primary
