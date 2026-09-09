"""CPQModel candidate resolution -- part of the Data-Table-conflict helper
cluster extracted from ``cpq/engine.py`` (Phase 4 step 1,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Stateless, purely-functional
wrapper over already-external ``data_table_resolver`` calls.
"""

from __future__ import annotations

from aryx.cpq.data_table.data_table_resolver import (
    discover_cpq_models_for_base_model as dt_discover_cpq_models_for_base_model,
    resolve_product_cpq_model_family as dt_resolve_product_cpq_model_family,
    resolve_product_cpq_models_from_rows as dt_resolve_product_cpq_models_from_rows,
)

_DEFAULT_CPQ_MODEL_CANDIDATES: tuple[str, ...] = ("APXNEXT", "APXNEXT_BOM")


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
    3. The static APXNEXT/APXNEXT_BOM fallback, unchanged, when none of the
       above applies (no workspace_id, or the product is in no ingested
       source at all) -- identical to this function's original behavior.

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
        primary = _DEFAULT_CPQ_MODEL_CANDIDATES
    if not (base_model and workspace_id is not None):
        return primary
    discovered = dt_discover_cpq_models_for_base_model(
        base_model, workspace_id, catalog_prefix, cache,
    )
    extra = tuple(cm for cm in discovered if cm not in primary)
    return primary + extra if extra else primary
