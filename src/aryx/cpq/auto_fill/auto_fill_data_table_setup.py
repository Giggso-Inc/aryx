"""`auto_fill`'s Data-Table-derived governance precomputation (Phase 4,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md), split out of the P0
setup block: grid-linked selectors, region-allow base-model resolution,
attrSequence-governed variable names, and hiding rules that can never
resolve because their backing Data Table is confirmed absent. Logic
unchanged from the original inline block.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from aryx.cpq.catalog_profile import resolve_base_model_vn
from aryx.cpq.engine import (
    _cpq_model_candidates,
    _hiding_rule_needs_missing_data_table,
    dt_attr_ever_governed_for_cpq_model,
    dt_governed_attr_names_for_base_model,
    dt_resolve_region_allow_value,
)
from aryx.cpq.region_and_noise_constants import region_for_country


@dataclass
class DataTableSetupResult:
    grid_selector_vns: set[str]
    bm_region_allow_value: str | None
    dt_governed_vns: set[str] = field(default_factory=set)
    dt_never_governed_anywhere: Callable[[str], bool] = lambda vn: False
    missing_data_target_ids: set[int] = field(default_factory=set)


def compute_data_table_setup(
    engine: Any, attrs: list[Any], filled: dict[str, str], country: str | None,
    workspace_id: int | None, catalog_prefix: str,
    dt_cache: dict[tuple[int, str], tuple], hiding_rules: list[Any] | None,
) -> DataTableSetupResult:
    # Selectors resolve_array_grid_links() confirmed drive a real
    # quantity attr (e.g. mountingTypeArray_viSoln -> the 6 mounting-
    # type quantities) are NOT cosmetic optional checkboxes even though
    # required="0" — silently defaulting them to empty would silently
    # skip a real BOM decision (docs/CPQ_SVX_LAYOUT_FLOW_AND_QUANTITY_
    # GRID_PLAN.md §5). Excluded from the optional-multi-select
    # auto-empty branch below so they're asked like any other real
    # question instead; every other optional multi-select is unaffected.
    grid_selector_vns = set(engine.resolve_array_grid_links(attrs).keys())

    # CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T1 Phase 3 "scoped" rollout:
    # resolved once, reused for every use of the Base Model key below --
    # avoids repeating the same CatalogProfile lookup 3x in one call.
    base_model_vn = resolve_base_model_vn(filled, workspace_id, catalog_prefix, dt_cache)

    # Base Model region-allow resolution (confirmed live, 2026-08-10):
    # NewCountryRegMapping-shaped ("region_rule") Data Table rows carry
    # a real per-(CPQModel, region[, country]) ALLOW default for
    # modelSelectionbaseModel_astro -- the same answer Oracle CPQ's own
    # "Set Base Model" recommendation rules compute at runtime against
    # `Oracle_BomItemMap` (a live table never present in any export
    # seen so far). Computed here, BEFORE base model is filled, using
    # only the PRIMARY (product-derived) CPQModel candidates -- unlike
    # the base-model-widened candidates below (which also widens by
    # base_model once one is chosen), there is no base model yet to
    # widen from. Only ever used when it resolves to exactly one value
    # (see `resolve_region_allow_value`'s tie-safe contract); otherwise
    # falls through to the unconditional always-ask anchor unchanged.
    bm_region_allow_value: str | None = None
    if workspace_id is not None and not filled.get(base_model_vn):
        bm_product = filled.get("productSelectionProduct_all", "")
        if bm_product:
            bm_country = filled.get("ultimateDestinationCountry") or country or ""
            bm_region = filled.get("modelSelectionRegion_astro") or (
                region_for_country(bm_country) if bm_country else ""
            )
            if bm_region:
                bm_primary_candidates = _cpq_model_candidates(
                    bm_product, workspace_id, catalog_prefix, dt_cache,
                )
                for bm_cm in bm_primary_candidates:
                    bm_v = dt_resolve_region_allow_value(
                        base_model_vn, bm_cm, bm_region,
                        workspace_id, catalog_prefix, dt_cache, country=bm_country,
                    )
                    if bm_v:
                        bm_region_allow_value = bm_v
                        break

    # Attrs a real ingested attrSequence Data Table confirms govern the
    # CURRENT base model (docs/CPQ_CARRIER_WIRELESS_FREQBAND_DATA_GAP_
    # PROOF_2026_08_07.md §1-§3, §9): must be treated as askable by §2c's
    # display-order gate the same way `grid_selector_vns` already is.
    # `dt_never_governed_anywhere` memoizes the per-vn "no attrSequence
    # row anywhere ever mentions this" check (real rows can be up to
    # tens of thousands; only compute once per attr actually reaching
    # this branch, not for every attr up front). Uses the full,
    # base-model-widened candidate set for VALUE RESOLUTION only — the
    # PRIMARY (product-derived only) candidates gate always-ask instead
    # (confirmed live 2026-08-09: a base model can be shared across
    # unrelated regional/federal siblings with zero real coverage under
    # the domestic order's own primary candidate, but real coverage
    # under a sibling — using the widened set to gate always-ask would
    # incorrectly inherit that sibling's entire governance scope).
    dt_governed_vns: set[str] = set()
    dt_candidates: tuple[str, ...] = ()
    if workspace_id is not None:
        dt_base_model = filled.get(base_model_vn, "")
        if dt_base_model:
            dt_product = filled.get("productSelectionProduct_all", "")
            dt_primary_candidates = _cpq_model_candidates(
                dt_product, workspace_id, catalog_prefix, dt_cache,
            )
            dt_candidates = _cpq_model_candidates(
                dt_product, workspace_id, catalog_prefix, dt_cache, base_model=dt_base_model,
            )
            for dt_cm in dt_primary_candidates:
                dt_scoped = dt_governed_attr_names_for_base_model(
                    dt_cm, dt_base_model, workspace_id, catalog_prefix, dt_cache,
                )
                if dt_scoped:
                    dt_governed_vns |= dt_scoped

    def dt_never_governed_anywhere(vn: str) -> bool:
        if not dt_candidates:
            return False
        return not any(
            dt_attr_ever_governed_for_cpq_model(
                cm, vn, workspace_id, catalog_prefix, dt_cache,
            )
            for cm in dt_candidates
        )

    # docs/CPQ_DATA_GAP_SKIP_AND_RULE_GOVERNED_BLIND_PICK_PLAN_2026_08_
    # 10.md -- attrs whose ONLY hiding rule structurally depends on a
    # confirmed-absent data table (_KNOWN_MISSING_DATA_TABLES) can never
    # have that rule resolve. hiding_rules=None (no caller passes it)
    # keeps this empty -- a complete no-op, identical to today's
    # behavior for every existing call site.
    missing_data_target_ids: set[int] = {
        rule.target_attr_id for rule in (hiding_rules or [])
        if _hiding_rule_needs_missing_data_table(rule, workspace_id)
    }

    return DataTableSetupResult(
        grid_selector_vns=grid_selector_vns,
        bm_region_allow_value=bm_region_allow_value,
        dt_governed_vns=dt_governed_vns,
        dt_never_governed_anywhere=dt_never_governed_anywhere,
        missing_data_target_ids=missing_data_target_ids,
    )
