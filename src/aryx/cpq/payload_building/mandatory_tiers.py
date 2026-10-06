"""Tier C (AttrSequence-Required) mandatory-attribute derivation for
`_is_mandatory_input_attr` (Phase 4 step 8 extraction from
``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

`_cpq_model_candidates`, `dt_governed_required_attr_names_for_base_
model` and `dt_resolve_whitelist_values` are all reached through the
engine MODULE object rather than imported by name: several tests patch
``aryx.cpq.engine._cpq_model_candidates`` /
``aryx.cpq.engine.dt_resolve_whitelist_values`` by dotted path (see
tests/test_cpq_config_data_attrseq_confirmed_gate_2026_08_19.py and
tests/test_cpq_substitute_util_get_constraint_vals_cache_2026_08_28.py),
and a frozen import-time reference here would silently bypass them.
`_RECOMMENDED_CONFIG_ONLY_VNS` stays a `CpqEngine` class attribute and
is read off the passed-in `engine`, preserving the original `self.`
lookup (subclass/instance overrides still win) -- passed as the
fallback to `model_policy.resolve_recommended_config_only_membership`
(CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T6 Phase 3) rather than
checked directly, so a real per-model policy entry can now govern
instead, without breaking that override contract.
"""

from __future__ import annotations

from typing import Any

from aryx.config import get_settings
from aryx.cpq import engine as _engine_module
from aryx.cpq.catalog_profile import resolve_base_model_vn
from aryx.cpq.payload_building.required_set import derive_required_vns
from aryx.cpq.model_policy import resolve_recommended_config_only_membership


def mandatory_tier_c_vns(
    engine: Any,
    filled: dict[str, str] | None,
    workspace_id: int | None,
    catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
    attrs: list[Any] | None = None,
    filled_source: dict[str, str] | None = None,
    filled_multi: dict[str, list[str]] | None = None,
    hidden_vns: set[str] | None = None,
    display_order: dict[str, int] | None = None,
    product_hint: str = "",
) -> frozenset[str]:
    """Tier C for `_is_mandatory_input_attr` (beautify/summary ONLY --
    NOT config_data, see docs/CPQ_ConfigData_Payload_Mandatory_Fix_
    Scope_2026_08_19.md for why): attribute names the real ingested
    AttrSequence Data Table flags optionOrReqFlag == "R" for the
    active (cpq_model, base_model) -- catching defaulted-but-editable
    Mandatory fields (Configuration Type, Software Bundles, Software
    Release, Solution Type, Duration, Application Services Bundle
    Duration, Wireless Carrier, Battery Type, Include a Spare,
    Country) that Tier A/B miss entirely because their filled_source
    is "rule"/"default", never "user" (docs/CPQ_Beautify_Mandatory_
    Section_Miscategorization_2026_08_19.md).

    "R" alone over-includes: many R-flagged attrs are auto-resolved by
    a Whitelist/Defaultinattr row (Shylaja Shetty's "Auto-Resolved by
    Data Tables" category) rather than ever being shown to the
    customer as editable. Excludes any R-flagged attr `resolve_
    whitelist_values` confirms has real constraint-shaped (Whitelist/
    Defaultinattr, pooled into the same table) coverage for this
    (cpq_model, base_model) -- same "genuinely unresolved, not merely
    silent" discipline `_suppress_ungoverned_attrs` already applies
    elsewhere. Also excludes `_RECOMMENDED_CONFIG_ONLY_VNS` (confirmed
    Recommended-Configuration-only attrs).

    Returns an empty frozenset (never None) when `filled`/
    `workspace_id`/base model/CPQModel candidates are unavailable --
    Tier C is purely additive, so "no coverage" must mean "adds
    nothing," not "unknown."
    """
    if not filled or workspace_id is None:
        return frozenset()
    if attrs and get_settings().cpq_required_set_enabled:
        # plan F6: beautify and the summary use the same derived set as config_data
        return derive_required_vns(
            engine, attrs, filled, filled_multi, filled_source, hidden_vns, display_order,
            workspace_id, catalog_prefix, product_hint, cache)
    base_model = filled.get(resolve_base_model_vn(filled, workspace_id, catalog_prefix, cache), "")
    if not base_model:
        return frozenset()
    product = filled.get("productSelectionProduct_all", "")
    cands = _engine_module._cpq_model_candidates(
        product, workspace_id, catalog_prefix, cache, base_model=base_model,
    )
    if not cands:
        return frozenset()
    required_names: set[str] = set()
    for cm in cands:
        names = _engine_module.dt_governed_required_attr_names_for_base_model(
            cm, base_model, workspace_id, catalog_prefix, cache,
        )
        if names:
            required_names |= names
    if not required_names:
        return frozenset()
    result: set[str] = set()
    for vn in required_names:
        if resolve_recommended_config_only_membership(
            vn, engine._RECOMMENDED_CONFIG_ONLY_VNS, cands,
        ):
            continue
        if any(
            _engine_module.dt_resolve_whitelist_values(
                cm, base_model, vn, filled, workspace_id, catalog_prefix, cache,
            ) is not None
            for cm in cands
        ):
            continue
        result.add(vn)
    return frozenset(result)
