"""Attr-visibility governance via the ingested attrSequence Data Table --
part of the Data-Table-conflict helper cluster extracted from
``cpq/engine.py`` (Phase 4 step 1,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Stateless, purely-functional
wrapper over already-external ``data_table_resolver`` calls.
"""

from __future__ import annotations

from aryx.cpq.catalog_profile import resolve_base_model_vn
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
#
# CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T6 Phase 3: passed to
# model_policy.resolve_confirmed_dead_attr_membership as the fallback
# rather than imported there -- model_policy.py importing this
# constant back would create a circular import; passing it as a
# parameter avoids that. `resolve_confirmed_dead_attr_membership`
# itself is imported LAZILY inside `_suppress_ungoverned_attrs` (not
# at module scope) for a second, confirmed-live reason: this module is
# loaded very early in `engine.py`'s own import chain (via `data_table_
# bridge/__init__.py`, near the top of engine.py), before `engine.py`
# has defined `_valid` -- a module-level import here transitively
# needs `fill_signature.py` -> `engine._valid`, which doesn't exist
# yet at that point, breaking the whole import chain (same pitfall
# already documented for the re-export hubs elsewhere in this
# codebase, e.g. `hiding_rules/apply.py`'s lazy `import aryx.cpq.engine
# as _engine_module`).
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

    CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T6 Phase 3: the
    `_CONFIRMED_DEAD_ATTRS` membership check below is resolved through
    `model_policy.resolve_confirmed_dead_attr_membership`, reusing
    `cands` (already resolved above) rather than re-deriving CPQ model
    candidates a second time.
    """
    from aryx.cpq.model_policy import resolve_confirmed_dead_attr_membership  # noqa: PLC0415

    if workspace_id is None:
        return attrs, set()
    base_model = filled.get(resolve_base_model_vn(filled, workspace_id, catalog_prefix, cache), "")
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
        elif resolve_confirmed_dead_attr_membership(vn, _CONFIRMED_DEAD_ATTRS, cands):
            suppressed.add(vn)
        elif not any(
            dt_attr_ever_governed_for_cpq_model(cm, vn, workspace_id, catalog_prefix, cache)
            for cm in cands
        ):
            visible.append(attr)
        else:
            suppressed.add(vn)
    return visible, suppressed
