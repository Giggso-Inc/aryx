"""Shared graph/RDB fetch primitives and family-name matching (Phase 4
step 11 extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

The small building blocks every other module in this package leans on:
`_batch_fetch` (the one RDB attribute fetch), `_is_layout_noise` (the
ontology-type filter), and `_match_family_name` (the BmPrdFamily /
BmCatalog name containment check shared by `_scope_to_catalog` and
`resolve_product_hint`).

`get_cpq_rdb` is read off the engine MODULE object -- many tests patch
``aryx.cpq.engine.get_cpq_rdb``, so a by-value import here would
silently break every one of them. `_LAYOUT_TYPE_FRAGMENTS`,
`_strip_catalog_name_noise` and `_HINT_MIN_PHRASE_LEN` are read the same
way.
"""

from __future__ import annotations

import re
from typing import Any

from aryx.cpq import engine as _engine_module


def _batch_fetch(
    engine: Any, entity_ids: list[int], workspace_id: int,
) -> dict[int, dict[str, Any]]:
    """Batch-fetch entity attribute JSON from the RDB (dialect-agnostic)."""
    return _engine_module.get_cpq_rdb().fetch_entity_attributes(
        entity_ids, workspace_id)


def _is_layout_noise(engine: Any, ontology_type: str) -> bool:
    t = (ontology_type or "").lower()
    return any(frag in t for frag in _engine_module._LAYOUT_TYPE_FRAGMENTS)


def _match_family_name(
    engine: Any, reader: Any, workspace_id: int, prefix: str, hint_norm: str,
) -> str | None:
    """The real BmPrdFamily/BmCatalog entity name under `prefix` whose
    normalized text substring-matches hint_norm, or None. Shared by
    _scope_to_catalog (family-only scoping) and resolve_product_hint
    (family + product-option scoping) — the family/catalog-name check
    is identical in both; only what else gets checked afterward differs.

    Requires the SHORTER side of the containment check to be at least
    _HINT_MIN_PHRASE_LEN chars — confirmed live that without this, a
    bare 2-char anchor reply like "US" (a country, not a product)
    spuriously matched inside "pCRBusinessLightDevices_bom" (the "us"
    in "business"), resolving a country name to a random catalog.
    """
    family_ents: list[dict] = []
    for family_type in (f"{prefix}BmPrdFamily", f"{prefix}BmCatalog"):
        # High limit, not a handful: a single product family can carry
        # dozens of BmCatalog entities (e.g. a MOTOTRBO/PCR family
        # spanning 70+ individual radio-model catalogs) — the model
        # actually matching product_hint (e.g. "autoSL3500E_BOM") can
        # sort anywhere in an unordered graph result, so a small limit
        # risks silently missing it and falling back to "ambiguous".
        family_ents.extend(
            reader.find_entities(ontology_type=family_type, limit=2000))
    if not family_ents:
        return None
    family_pg = engine._batch_fetch([e["id"] for e in family_ents], workspace_id)
    for fent in family_ents:
        fname = str(
            family_pg.get(fent["id"], {}).get("name") or fent.get("name") or ""
        )
        fname_norm = _engine_module._strip_catalog_name_noise(
            re.sub(r"[^a-z0-9]", "", fname.lower())
        )
        if not fname_norm:
            continue
        shorter_len = min(len(fname_norm), len(hint_norm))
        if shorter_len < _engine_module._HINT_MIN_PHRASE_LEN:
            continue
        if fname_norm in hint_norm or hint_norm in fname_norm:
            return fname
    return None
