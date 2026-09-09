"""Hidden-master-string computation via the ingested attrSequence Data
Table -- part of the Data-Table-conflict helper cluster extracted from
``cpq/engine.py`` (Phase 4 step 1,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Stateless, purely-functional
wrapper over already-external ``data_table_resolver`` calls.
"""

from __future__ import annotations

from aryx.cpq.data_table_bridge.candidates import _cpq_model_candidates
from aryx.cpq.data_table.data_table_resolver import (
    governed_attr_names_for_base_model as dt_governed_attr_names_for_base_model,
)
from aryx.cpq.state import ConfigAttr


def _compute_hidden_master_string(
    filled: dict[str, str],
    workspace_id: int | None,
    catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
    attrs: list[ConfigAttr] | None = None,
    var_name: str = "hiddenMasterStringForAstroPortable_astro",
    separator_var_name: str = "hidddenRecordSeparator_allFamilly",
) -> str | None:
    """Real, generic replacement for a real BM script this catalog can't
    execute ("Set Hidden Master String For Astro Portable" and its
    siblings): the delimited list of attribute names the ingested
    attrSequence Data Table says apply to the current product's
    CPQModel/BaseModel pair. Reuses the SAME governed-name computation
    `_suppress_ungoverned_attrs` runs. Returns `None` (leave caller's
    `filled` untouched) when `workspace_id`/Product/Base Model aren't
    resolved, or no CPQModel candidate has ANY attrSequence coverage.
    """
    if workspace_id is None:
        return None
    product = filled.get("productSelectionProduct_all", "")
    base_model = filled.get("modelSelectionbaseModel_astro", "")
    if not product or not base_model:
        return None
    cands = _cpq_model_candidates(
        product, workspace_id, catalog_prefix, cache, base_model=base_model,
    )
    if not cands:
        return None
    scoped_name_sets = [
        dt_governed_attr_names_for_base_model(
            cm, base_model, workspace_id, catalog_prefix, cache,
        )
        for cm in cands
    ]
    if not any(s is not None for s in scoped_name_sets):
        return None
    governed_names: set[str] = set()
    for s in scoped_name_sets:
        if s:
            governed_names |= s

    sep = filled.get(separator_var_name, "")
    if not sep and attrs:
        sep_attr = next(
            (a for a in attrs if a.variable_name == separator_var_name), None,
        )
        if sep_attr and sep_attr.default_value:
            sep = sep_attr.default_value
    if not sep:
        sep = "@@@"

    if not governed_names:
        return ""
    return "".join(f"{name}{sep}" for name in sorted(governed_names))
