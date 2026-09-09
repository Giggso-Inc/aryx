"""`load_product_config`'s Step 3c override redirection (Phase 4, docs/
RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). See `apply_override_
redirection`'s own docstring below for the full contract. Logic
unchanged from the original inline block.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.engine import _catalog_prefix, logger
from aryx.cpq.product_config.product_config_entities import _norm


def apply_override_redirection(
    engine: Any, reader: Any, workspace_id: int, attr_ents: list[dict],
    attr_pg: dict[int, dict], all_type_names: list[str], resolved_catalog_prefix: str,
    fk_menu_pool: dict[int, dict] | None,
    neighbor_map: dict[int, list[int]], all_menu_ids: list[int],
) -> None:
    """Mutates `neighbor_map`/`all_menu_ids` in place.

    Nothing in this pipeline read the bm_config_att_override construct
    before (confirmed live: zero references to it anywhere in the
    codebase) — every attr's options came ONLY from its own base
    entity's graph neighbors, so an override-only option was silently
    invisible everywhere (the answer prompt, apply_answer matching,
    every constraint rule's allowed-value intersection).

    Live-confirmed bug (2026-07-28): productSelectionProduct_all's base
    entity (native id 39427019) neighbors a stale bm_menu_item set that
    repeats "APX NEXT ENHANCED" many times but never carries "APX NEXT
    XE 4G LTE PLUS 5G" — while a bm_config_att_override entity for the
    SAME native attribute_id neighbors the complete, catalog-correct
    list containing both. A real constraint rule (Hardware-Version-
    keyed) correctly narrowed to both values, but the numbered prompt
    only ever showed the one the base entity's own menu list happened
    to carry.
    Purely additive and structural: detected via ontology_type suffix
    (no hardcoded catalog/attr names) and merged (never replaces) into
    the base entity's own neighbor list — the (item_value) dedup in
    `product_config_menu_build.py` already absorbs any item repeated
    in both sets, so this only ever ADDS options a base-only read
    would have missed, never removes one a real customer answer relies on.
    """
    override_types = [
        t for t in all_type_names
        if _norm(t).endswith("configattoverride")
        and (not resolved_catalog_prefix
             or _catalog_prefix(t) == resolved_catalog_prefix)
    ]
    if not override_types:
        return
    override_ents: list[dict] = []
    for ot in override_types:
        offset = 0
        while True:
            page = reader.find_entities(ontology_type=ot, limit=500, offset=offset)
            override_ents.extend(page)
            if len(page) < 500:
                break
            offset += 500
    if not override_ents:
        return
    override_pg = engine._batch_fetch([e["id"] for e in override_ents], workspace_id)
    # base attr's own native id -> owning entity_id(s), same
    # "native id can own 2+ entity_ids" reality the orphan
    # FK-fallback above already accounts for.
    base_eids_by_native_id: dict[str, list[int]] = {}
    for e in attr_ents:
        rid = attr_pg.get(e["id"], {}).get("id")
        if rid is not None:
            base_eids_by_native_id.setdefault(str(rid), []).append(e["id"])
    for oe in override_ents:
        oeid = oe["id"]
        target_native_id = str(override_pg.get(oeid, {}).get("attribute_id") or "")
        owner_eids = base_eids_by_native_id.get(target_native_id)
        if not owner_eids:
            continue
        try:
            override_neighbors = reader.neighbors(oeid)
        except Exception:
            logger.debug(
                "cpq: neighbor fetch failed for override attr %d", oeid, exc_info=True)
            continue
        override_menu_ids = [
            n["id"] for n in override_neighbors
            if "menuitem" in (n.get("type") or "").lower().replace("_", "")
            and (not resolved_catalog_prefix
                 or _catalog_prefix(n.get("type") or "") == resolved_catalog_prefix)
        ]
        if not override_menu_ids:
            # FK fallback (2026-08-17, live-confirmed): same class
            # of gap as the base-attr orphan_eids fallback above,
            # but for override entities -- a bm_config_att_override
            # can have a real Postgres row and real bm_menu_item
            # children correctly linked via the ref_id property,
            # yet zero graph edges (confirmed live: override
            # entity 2251385 for productSelectionProduct_all has
            # 325 real menu items keyed by ref_id == its own
            # native id, but reader.neighbors() returns empty,
            # silently dropping "APX NEXT XE 4G LTE PLUS 5G" from
            # the Product menu). Detected structurally (empty
            # graph neighbors on an override row that exists in
            # Postgres), never by attr/catalog name, so it
            # self-heals for any override hitting the same gap.
            # Reuses the same menu-item pool as the base-attr
            # fallback (fetched lazily here if that fallback
            # didn't already run this call).
            if fk_menu_pool is None:
                menu_types_all = [
                    t for t in all_type_names
                    if _norm(t).endswith("menuitem")
                    and (not resolved_catalog_prefix
                         or _catalog_prefix(t) == resolved_catalog_prefix)
                ]
                fk_menu_ents_all: list[dict] = []
                for mt in menu_types_all:
                    off = 0
                    while True:
                        page = reader.find_entities(
                            ontology_type=mt, limit=2000, offset=off)
                        fk_menu_ents_all.extend(page)
                        if len(page) < 2000:
                            break
                        off += 2000
                fk_menu_pool = engine._batch_fetch(
                    [m["id"] for m in fk_menu_ents_all], workspace_id)
            override_native_id = str(override_pg.get(oeid, {}).get("id") or "")
            override_menu_ids = [
                mid for mid, mdata in fk_menu_pool.items()
                if str(mdata.get("ref_id") or "") == override_native_id
            ]
            if not override_menu_ids:
                continue
        for owner_eid in owner_eids:
            # Prepended, not appended: the override is BM's
            # authoritative, catalog-specific replacement for
            # this attr's menu — when the same item_value exists
            # in both (confirmed live: "APX NEXT ENHANCED" on the
            # base list displays as "APX NEXT Enhanced", but the
            # override's own copy of that same item_value
            # displays as "APX NEXT (4G LTE+5G)"), the override's
            # display must win, not silently coexist as a
            # second, differently-labeled entry for an identical
            # code. Processing override entries first lets the
            # item_value-keyed dedup below keep only the first
            # (override) occurrence.
            neighbor_map[owner_eid] = override_menu_ids + neighbor_map.get(owner_eid, [])
        all_menu_ids.extend(override_menu_ids)
