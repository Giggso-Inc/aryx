"""Product-option-list fetching (Phase 4 step 11 extraction from
``cpq/engine.py`` -- see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

`_batch_fetch`, `_PRODUCT_FIELD_FALLBACK_RE`, and
`_PRODUCT_FIELD_FALLBACK_HINT_RE` go back through the passed-in
`engine` instance.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.children_wrappers import through_children_wrappers


def fetch_product_option_list(
    engine: Any, reader: Any, workspace_id: int, prefix: str,
) -> list[tuple[str, str]]:
    """(item_value, display_name) options for one catalog's customer-
    facing product-name field.

    Confirmed live: both currently-ingested catalogs (ApxNextConfig,
    Sl3500EConfig) name this field productSelectionProduct_all — this is
    the field product-LINE VARIANTS (e.g. "APX NEXT Enhanced", "DGM
    8500e") actually live in, never in BmPrdFamily/BmCatalog names
    (confirmed: "APX NEXT Enhanced" matches no real family/catalog name
    in this catalog at all).

    A THIRD catalog using a different field name for the same concept
    is not hardcoded around: when no attr is literally named
    productSelectionProduct_all, falls back to a structural signal —
    any attr whose variable_name matches both "product" and
    ("select"|"line") (case-insensitive), same naming convention as
    both known catalogs' own field. Multiple candidates pick the one
    with the MOST real menu options (product-variant selectors are
    high-cardinality dropdowns by nature — confirmed 325 real options
    on this catalog's own field), a deterministic tie-break within an
    already-narrowed, name-matched candidate set rather than a blind
    guess across the whole catalog.

    Only called for infrequent product-hint resolution (first message,
    anchor-answer validation) — not the hot per-turn path — so a full
    per-catalog attr scan here (mirroring load_product_config's own
    entity+Postgres fetch) is an acceptable, one-off cost.
    """
    try:
        attr_ents = reader.find_entities(
            ontology_type=f"{prefix}BmConfigAttr", limit=500)
    except Exception:
        return []
    if not attr_ents:
        return []
    attr_pg = engine._batch_fetch([e["id"] for e in attr_ents], workspace_id)
    target_id = None
    fallback_ids: list[int] = []
    for ent in attr_ents:
        pg = attr_pg.get(ent["id"], {})
        vn = str(
            pg.get("variable_name") or pg.get("name") or ent.get("name") or ""
        ).strip()
        if vn == "productSelectionProduct_all":
            target_id = ent["id"]
            break
        if (engine._PRODUCT_FIELD_FALLBACK_RE.search(vn)
                and engine._PRODUCT_FIELD_FALLBACK_HINT_RE.search(vn)):
            fallback_ids.append(ent["id"])
    if target_id is None and fallback_ids:
        # One batched call instead of one reader.neighbors() per
        # candidate — was up to hundreds of round-trips on catalogs with
        # many attrs matching the fallback regex (mirrors the
        # neighbors_batch() fix already applied to load_product_config's
        # own attribute-neighbor loop a few hundred lines below).
        try:
            neighbors_by_id = reader.neighbors_batch(fallback_ids)
        except Exception:
            neighbors_by_id = {}
        target_id = max(
            fallback_ids, key=lambda eid: len(neighbors_by_id.get(eid, []))
        )
    if target_id is None:
        return []
    try:
        neighbors = reader.neighbors(target_id)
        neighbors = through_children_wrappers(reader, {target_id: neighbors})[target_id]
    except Exception:
        return []
    menu_ids = [
        n["id"] for n in neighbors
        if "menuitem" in (n.get("type") or "").lower().replace("_", "")
    ]
    if not menu_ids:
        return []
    menu_pg = engine._batch_fetch(menu_ids, workspace_id)
    options: list[tuple[str, str]] = []
    for mid in menu_ids:
        ma = menu_pg.get(mid, {})
        iv = str(ma.get("item_value") or "").strip()
        dt = str(ma.get("item_text") or ma.get("name") or iv).strip()
        if iv:
            options.append((iv, dt))
    return options
