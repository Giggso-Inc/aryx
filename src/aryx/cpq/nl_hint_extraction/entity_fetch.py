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


def _match_basemodel_to_config_name(
    engine: Any, reader: Any, workspace_id: int, prefix: str, hint_norm: str,
    rdb_cache: dict | None = None,
) -> str | None:
    """The real Basemodeltoconfig displayModel name whose normalized text
    substring-matches hint_norm (longest match wins), or None. Port of
    dev-rv-msi #351/#365/#366; only called when
    `cpq_basemodel_display_name_resolution_enabled` is on.

    Basemodeltoconfig names specific devices (e.g. "APX 900" -> APX900),
    unlike family-level BmPrdFamily/BmCatalog names. Same
    _HINT_MIN_PHRASE_LEN short-string guard as `_match_family_name`.

    Source order: the graph under `{prefix}Basemodeltoconfig`, then the bare
    `Basemodeltoconfig` (the table is ingested unprefixed, #365), and when
    both are empty the RDB via `fetch_entities_by_exact_type` (it is a CSV
    Data Table that is never graph-ingested, #366). The RDB fallback ignores
    `prefix`, so `rdb_cache` (a dict the caller owns for one resolve call)
    memoizes its rows per workspace and the same rows are not re-fetched
    for every catalog prefix.
    """
    try:
        rows = reader.find_entities(
            ontology_type=f"{prefix}Basemodeltoconfig", limit=2000)
        if not rows:
            rows = reader.find_entities(
                ontology_type="Basemodeltoconfig", limit=2000)
    except Exception:
        rows = []
    if rows:
        row_pg = engine._batch_fetch([e["id"] for e in rows], workspace_id)
    else:
        cache_key = ("basemodel_to_config_rdb_rows", workspace_id)
        if rdb_cache is not None and cache_key in rdb_cache:
            row_pg = rdb_cache[cache_key]
        else:
            try:
                pg_rows = _engine_module.get_cpq_rdb().fetch_entities_by_exact_type(
                    workspace_id, "Basemodeltoconfig")
            except Exception:
                return None
            row_pg = {eid: attrs for eid, attrs in (pg_rows or [])}
            if rdb_cache is not None:
                rdb_cache[cache_key] = row_pg
        if not row_pg:
            return None
    best_match: str | None = None
    best_len = 0
    for pg in row_pg.values():
        display_name = str((pg or {}).get("displayModel") or "").strip()
        if not display_name:
            continue
        name_norm = _engine_module._normalize_for_hint(display_name)
        if not name_norm:
            continue
        shorter_len = min(len(name_norm), len(hint_norm))
        if shorter_len < _engine_module._HINT_MIN_PHRASE_LEN:
            continue
        if name_norm in hint_norm or hint_norm in name_norm:
            # Longest displayModel wins ("APX 900 FLASHPORT" over "APX 900").
            if len(name_norm) > best_len:
                best_match = display_name
                best_len = len(name_norm)
    return best_match
