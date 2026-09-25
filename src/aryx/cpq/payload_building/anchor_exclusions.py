"""`config_data`-only structural-anchor exclusion set -- the inverse of
Tier C (Phase 4 step 8 extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

`_cpq_model_candidates`, `dt_resolve_region_allow_value` and
`_COUNTRY_TO_REGION` are read through the engine MODULE object rather
than imported by name: the first two are patched by dotted path in
tests/test_cpq_config_data_attrseq_confirmed_gate_2026_08_19.py, and
`_COUNTRY_TO_REGION` is defined further down ``engine.py`` than the
import line that pulls this package in, so the lookup must happen at
call time either way.
"""

from __future__ import annotations

from typing import Any

from aryx.config import get_settings
from aryx.cpq import engine as _engine_module
from aryx.cpq.catalog_profile import shadow_check_role_vn
from aryx.cpq.region_and_noise_constants import region_for_country
from aryx.cpq.state import ConfigAttr


def _data_table_resolved_anchor_vns(
    engine: Any,
    filled: dict[str, str] | None,
    attrs: list[ConfigAttr] | None,
    workspace_id: int | None,
    catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
    country: str = "",
) -> frozenset[str]:
    """`config_data`-only exclusion set for Tier A's "basemodel"/
    "selectmodel" fragment match (docs/CPQ_ConfigData_Payload_
    Mandatory_Fix_Scope_2026_08_19.md). The inverse of
    `mandatory_tier_c_vns` -- an EXCLUDE set, not an include set.

    Live-confirmed: modelSelectionbaseModel_astro looks like a real
    menu-type attribute at the catalog level (menu_type=1), and Tier A
    treats any "basemodel"/"selectmodel"-fragment match as an
    unconditional structural anchor -- but it is not a real UI
    submission (missing from the actual APX NEXT screenshot AND from
    a real target config_data payload). Its value is 100% derived
    from Country + Hardware Version + Product via the ingested
    NewCountryRegMapping (region-rule-shaped) Data Table --
    `resolve_region_allow_value`'s own docstring names this exact
    attribute as its worked example. Reuses the identical (product,
    region, country) -> CPQModel-candidate -> region-rule resolution
    pattern already live elsewhere in this file (see the
    `_bm_region_allow_value` block above, used for a different
    purpose -- pre-filling Base Model before it's asked).

    For each attribute in `attrs` whose name fragment-matches
    "basemodel"/"selectmodel", checks whether ANY resolved CPQModel
    candidate's region-rule row deterministically resolves it -- if
    so, it is not a genuine anchor decision and is added to the
    exclude set. Returns `frozenset()` (never `None`) when `filled`/
    `attrs`/`workspace_id`/product/region are unavailable -- purely
    subtractive, so "no coverage" must mean "no exclusions," never a
    guess.

    CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T1 Phase 3 pilot slice:
    also runs a shadow-only `catalog_profile.shadow_check_role_vn` for
    the "Region" role here -- gated off by default, log-only, never
    affects `region`/the returned exclude set.
    """
    if not filled or not attrs or workspace_id is None:
        return frozenset()
    product = filled.get("productSelectionProduct_all", "")
    if not product:
        return frozenset()
    # CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T1 Phase 3 pilot follow-up:
    # shadow-only comparison against what a CatalogProfile-style resolver
    # would give for the "Region" role under this product's CPQ model(s) --
    # never changes `region` below. Gated off by default, same as the
    # Base Model pilot in ask_invalidate_stale_base_model.py.
    if get_settings().catalog_profile_shadow_check_enabled:
        shadow_check_role_vn(
            "Region", "modelSelectionRegion_astro", product, workspace_id, catalog_prefix, cache,
        )
    resolved_country = filled.get("ultimateDestinationCountry") or country or ""
    region = filled.get("modelSelectionRegion_astro") or (
        region_for_country(resolved_country, _engine_module._COUNTRY_TO_REGION)
        if resolved_country else ""
    )
    if not region:
        return frozenset()
    cands = _engine_module._cpq_model_candidates(
        product, workspace_id, catalog_prefix, cache)
    if not cands:
        return frozenset()
    result: set[str] = set()
    for attr in attrs:
        vn_flat = attr.variable_name.lower().replace("_", "")
        if "basemodel" not in vn_flat and "selectmodel" not in vn_flat:
            continue
        for cm in cands:
            if _engine_module.dt_resolve_region_allow_value(
                attr.variable_name, cm, region, workspace_id, catalog_prefix, cache,
                country=resolved_country,
            ):
                result.add(attr.variable_name)
                break
    return frozenset(result)
