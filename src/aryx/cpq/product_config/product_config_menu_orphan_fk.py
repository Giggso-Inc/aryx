"""`load_product_config`'s Step 3b orphan FK fallback (Phase 4, docs/
RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md): resolves menu options for
attrs with a real Postgres bm_config_attr row but no graph edge to their
menu items, via the bm_config_attr_id FK instead. Logic unchanged from
the original inline block.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.engine import _catalog_prefix
from aryx.cpq.product_config.product_config_entities import _norm


def resolve_orphan_menu_items(
    engine: Any, reader: Any, workspace_id: int, attr_pg: dict[int, dict],
    orphan_eids: list[int], resolved_catalog_prefix: str, all_type_names: list[str],
    neighbor_map: dict[int, list[int]], all_menu_ids: list[int],
) -> dict[int, dict] | None:
    """Mutates `neighbor_map`/`all_menu_ids` in place. Returns the fetched
    menu-item pool (reused by the override fallback below) or None when
    there was nothing to resolve.
    """
    if not orphan_eids:
        return None
    # A real BM native id can legitimately own more than one graph
    # entity_id (confirmed live: SL3500e ingested
    # ultimateDestinationCountry twice under distinct entity_ids
    # 188302/212455, both real id 39426962) — a plain 1:1 dict here
    # would silently keep only the last-iterated entity_id and drop
    # the other's options entirely. Map real id -> ALL owning
    # entity_ids so every duplicate gets the same menu options.
    orphan_real_ids: dict[str, list[int]] = {}
    for eid in orphan_eids:
        rid = attr_pg.get(eid, {}).get("id")
        if rid is not None:
            orphan_real_ids.setdefault(str(rid), []).append(eid)
    if not orphan_real_ids:
        return None

    menu_types = [
        t for t in all_type_names
        if _norm(t).endswith("menuitem")
        and (not resolved_catalog_prefix
             or _catalog_prefix(t) == resolved_catalog_prefix)
    ]
    # Paginate past find_entities' per-call cap (ARYX_GRAPH_QUERY_LIMIT,
    # confirmed live at 2000) — SL3500e alone ships >2000 bm_menu_item
    # rows, so a single capped call silently truncated to whichever
    # rows the graph happened to return first, missing e.g.
    # ultimateDestinationCountry's country list entirely.
    fk_menu_ents: list[dict] = []
    page_size = 2000
    for mt in menu_types:
        offset = 0
        while True:
            page = reader.find_entities(ontology_type=mt, limit=page_size, offset=offset)
            fk_menu_ents.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
    fk_menu_pg = engine._batch_fetch([m["id"] for m in fk_menu_ents], workspace_id)
    for mid, mdata in fk_menu_pg.items():
        owner_eids = orphan_real_ids.get(str(mdata.get("bm_config_attr_id") or ""))
        if not owner_eids:
            continue
        for owner_eid in owner_eids:
            neighbor_map.setdefault(owner_eid, []).append(mid)
        all_menu_ids.append(mid)
    return fk_menu_pg
