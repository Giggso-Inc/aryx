"""CPQModel candidate resolution -- part of the Data-Table-conflict helper
cluster extracted from ``cpq/engine.py`` (Phase 4 step 1,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Stateless, purely-functional
wrapper over already-external ``data_table_resolver`` calls.
"""

from __future__ import annotations

import logging

from aryx.config import get_settings
from aryx.cpq import model_resolution as _model_resolution
from aryx.cpq.data_table.data_table_resolver import (
    discover_cpq_models_for_base_model as dt_discover_cpq_models_for_base_model,
    resolve_product_cpq_model_family as dt_resolve_product_cpq_model_family,
    resolve_product_cpq_models_from_rows as dt_resolve_product_cpq_models_from_rows,
)

logger = logging.getLogger(__name__)

_DEFAULT_CPQ_MODEL_CANDIDATES: tuple[str, ...] = ("APXNEXT", "APXNEXT_BOM")


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
    except Exception:  # noqa: BLE001 -- never break candidate resolution
        logger.exception("cpq: model_scope candidate prepend failed product_name=%r", product_name)
        return primary


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
        else:
            primary = _DEFAULT_CPQ_MODEL_CANDIDATES
    original = primary
    primary = _prepend_resolved_model(primary, product_name, base_model)
    if not (base_model and workspace_id is not None):
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
        return head + extra + original
    return primary + extra if extra else primary
