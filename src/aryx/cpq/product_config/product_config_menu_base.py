"""`load_product_config`'s Step 3 main neighbor pass (Phase 4, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md): batch-collect each attr's own graph-
neighbor menu items, then detect attrs with a real menu_type but zero
neighbors (fed to the orphan FK fallback). Logic unchanged from the
original inline block.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.engine import _catalog_prefix, logger


def collect_base_menu_neighbors(
    reader: Any, attr_ents: list[dict], attr_pg: dict[int, dict],
    resolved_catalog_prefix: str,
) -> tuple[dict[int, list[int]], list[int], list[int]]:
    """Returns (neighbor_map, all_menu_ids, orphan_eids)."""
    # Step 3 — collect ALL menu item IDs from the graph in one batched pass,
    # then batch-fetch all relational data in a single query.
    # Previously this loop was capped at [:150], causing attrs beyond that
    # position (e.g. hWVersion_astro at position 236) to silently get no
    # options. Two-pass approach eliminates the cap; neighbors_batch()
    # (rather than one reader.neighbors() call per attr) eliminates the
    # graph-side N+1 — confirmed live at ~750ms/round-trip against Oracle
    # ADB, so a 235-attr product previously took ~3 minutes on this step
    # alone (FalkorDB's in-process round-trips hid the same N+1 cost).
    neighbor_map: dict[int, list[int]] = {}  # attr_entity_id → [menu_entity_ids]
    all_menu_ids: list[int] = []
    # AttributeError fallback keeps OracleGraphReader and every test double
    # lacking neighbors_batch working unchanged, same pattern as
    # distinct_types above -- any OTHER failure also degrades to the
    # per-entity loop rather than silently dropping every attr's menu
    # items (an empty {} fallback here would surface as products losing
    # all their options, not just running slower).
    try:
        neighbors_by_attr = reader.neighbors_batch([e["id"] for e in attr_ents])
    except Exception:
        logger.debug("cpq: batch neighbor fetch failed", exc_info=True)
        neighbors_by_attr = None
    for ent in attr_ents:
        eid = ent["id"]
        try:
            neighbors = (
                neighbors_by_attr.get(eid, []) if neighbors_by_attr is not None
                else reader.neighbors(eid)
            )
        except Exception:
            logger.debug("cpq: neighbor fetch failed for attr %d", eid, exc_info=True)
            neighbors = []
        # reader.neighbors_batch() has no catalog awareness — for attrs whose
        # native id is reused across catalogs (e.g. productSelectionProduct_all,
        # confirmed live to have separate BmMenuItem sets per catalog under
        # the same native id) this returns menu items from EVERY catalog in
        # the workspace, not just the one resolved above. Scope by the same
        # resolved_catalog_prefix already used for attr_types. Skip the
        # filter when resolved_catalog_prefix is "" — per _scope_to_catalog,
        # that means scoping didn't narrow to one catalog, so no filter
        # should be applied (same convention as the attr-type scoping above).
        menu_ids = [
            n["id"] for n in neighbors
            if "menuitem" in (n.get("type") or "").lower().replace("_", "")
            and (
                not resolved_catalog_prefix
                or _catalog_prefix(n.get("type") or "") == resolved_catalog_prefix
            )
        ]
        if menu_ids:
            neighbor_map[eid] = menu_ids
            all_menu_ids.extend(menu_ids)

    # Step 3b — FK fallback for attrs with a real Postgres bm_config_attr
    # row but NO graph edge to their menu items (confirmed live: SVX's
    # modelSelectionSelectModel_viSoln has 4 real bm_menu_item rows in
    # Postgres, correctly FK'd via bm_config_attr_id, but zero FalkorDB
    # neighbors — a graph-ingestion gap, not a rule-driven/constrained
    # menu). Detected purely structurally (menu_type present + empty
    # neighbor_map entry), never by attr/catalog name, so it self-heals
    # for any future XML with the same ingestion gap.
    orphan_eids = [
        e["id"] for e in attr_ents
        if e["id"] not in neighbor_map
        and str(attr_pg.get(e["id"], {}).get("menu_type") or "") == "1"
    ]
    return neighbor_map, all_menu_ids, orphan_eids
