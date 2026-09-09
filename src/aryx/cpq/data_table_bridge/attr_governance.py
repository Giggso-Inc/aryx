"""Attr-visibility governance via the ingested attrSequence Data Table --
part of the Data-Table-conflict helper cluster extracted from
``cpq/engine.py`` (Phase 4 step 1,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Stateless, purely-functional
wrapper over already-external ``data_table_resolver`` calls.
"""

from __future__ import annotations

from aryx.cpq.data_table_bridge.candidates import _cpq_model_candidates
from aryx.cpq.data_table.data_table_resolver import (
    attr_ever_governed_for_cpq_model as dt_attr_ever_governed_for_cpq_model,
    governed_attr_names_for_base_model as dt_governed_attr_names_for_base_model,
)
from aryx.cpq.state import ConfigAttr

# Core navigational anchors -- never suppressed by the attrSequence-driven
# "doesn't apply to this base model" check, even when a real ingested
# attrSequence table has no row for one of these at the active base model.
_NEVER_SUPPRESS_FRAGMENTS: frozenset[str] = frozenset({
    "basemodel", "product", "country", "region", "hwversion", "hardwareversion",
})

# Attrs confirmed live (2026-08-16) to be orphaned/legacy -- zero
# attrSequence rows anywhere, but native CPQ never renders them for any
# APX NEXT product. Narrow allowlist, not a change to the general silence
# carve-out below.
_CONFIRMED_DEAD_ATTRS: frozenset[str] = frozenset({
    "modelSelectionFrequencyBands_astro",
    "modelSelectionFrequencyBandPlus_astro",
})


def _suppress_ungoverned_attrs(
    attrs: list[ConfigAttr], filled: dict[str, str],
    workspace_id: int | None, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> tuple[list[ConfigAttr], set[str]]:
    """Drop attrs the real ingested attrSequence Data Table confidently
    says do NOT belong to the active base model -- returns (visible,
    suppressed_variable_names). Only ever REMOVES an attr when at least one
    CPQModel candidate has attrSequence coverage for this exact base model
    AND none of them say this one applies AND at least one candidate's
    attrSequence table mentions this attr name for SOME base model. An attr
    with NO attrSequence coverage anywhere is left visible instead (silence
    is not a confident exclusion). `None`/no `workspace_id` is a complete
    no-op.
    """
    if workspace_id is None:
        return attrs, set()
    base_model = filled.get("modelSelectionbaseModel_astro", "")
    if not base_model:
        return attrs, set()
    product = filled.get("productSelectionProduct_all", "")
    cands = _cpq_model_candidates(
        product, workspace_id, catalog_prefix, cache, base_model=base_model,
    )
    if not cands:
        return attrs, set()

    scoped_name_sets = [
        dt_governed_attr_names_for_base_model(
            cm, base_model, workspace_id, catalog_prefix, cache,
        )
        for cm in cands
    ]
    if not any(s is not None for s in scoped_name_sets):
        return attrs, set()
    governed_names: set[str] = set()
    for s in scoped_name_sets:
        if s:
            governed_names |= s

    visible: list[ConfigAttr] = []
    suppressed: set[str] = set()
    for attr in attrs:
        vn = attr.variable_name
        vn_flat = vn.lower().replace("_", "")
        if any(frag in vn_flat for frag in _NEVER_SUPPRESS_FRAGMENTS):
            visible.append(attr)
        elif vn in governed_names:
            visible.append(attr)
        elif vn in _CONFIRMED_DEAD_ATTRS:
            suppressed.add(vn)
        elif not any(
            dt_attr_ever_governed_for_cpq_model(cm, vn, workspace_id, catalog_prefix, cache)
            for cm in cands
        ):
            visible.append(attr)
        else:
            suppressed.add(vn)
    return visible, suppressed
