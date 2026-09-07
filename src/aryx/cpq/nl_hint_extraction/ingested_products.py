"""The workspace's live ingested-product inventory (Phase 4 step 11
extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Both directions of the "which products exist here?" question, read live
from the graph with no hardcoded product list:
`_ingested_product_names` (the BmPrdFamily/BmCatalog family names) and
`ingested_product_alias_map` (every bm_catalog tree alias mapped to its
owning family -- the only catalog-DISCRIMINATING product signal, see
that function's docstring).

`_catalog_prefix` is read off the engine MODULE object so the original
bare-global reference resolves at call time; `_batch_fetch` goes back
through the passed-in `engine` instance.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq import engine as _engine_module


def _ingested_product_names(
    engine: Any, reader: Any, workspace_id: int,
) -> list[str]:
    """Real product/family display names for every catalog currently
    ingested in this workspace — read live from the graph, no hardcoded
    product list.

    Mirrors the BmPrdFamily/BmCatalog lookup _scope_to_catalog already
    does to resolve a hint back to one catalog (see its docstring); here
    we go the other direction — enumerate every ingested catalog's own
    name so a mention of ANY currently-ingested product can be
    recognised, not just ones anticipated when this code was written.
    Returns [] (never raises) when the reader can't answer distinct_types
    or no family/catalog entity is found — callers must treat that as
    "no dynamic candidates available", not an error.
    """
    try:
        all_type_names = reader.distinct_types()
    except AttributeError:
        return []
    # "" (no source-stem prefix) is a legitimate catalog scope too — a
    # workspace with only one ingested catalog may have unprefixed type
    # names (_scope_to_catalog treats this the same way: len(prefixes)<=1
    # returns that one prefix, even when it's ""). Excluding "" here
    # would silently skip the single-catalog case entirely.
    prefixes = sorted({_engine_module._catalog_prefix(t) for t in all_type_names})
    names: list[str] = []
    for prefix in prefixes:
        family_ents: list[dict] = []
        for family_type in (f"{prefix}BmPrdFamily", f"{prefix}BmCatalog"):
            family_ents.extend(
                reader.find_entities(ontology_type=family_type, limit=50))
            if family_ents:
                break
        if not family_ents:
            continue
        family_pg = engine._batch_fetch([e["id"] for e in family_ents], workspace_id)
        for fent in family_ents:
            fname = str(
                family_pg.get(fent["id"], {}).get("name") or fent.get("name") or ""
            ).strip()
            if fname:
                names.append(fname)
    return names


def ingested_product_alias_map(
    engine: Any, reader: Any, workspace_id: int,
) -> dict[str, str]:
    """{alias → owning family name} for every catalog in this workspace.

    _ingested_product_names only surfaces the BmPrdFamily names (e.g.
    "aSTRO25_bom", "videoSolutions_BOM") — internal BOM identifiers a
    client rarely says. But each export also carries its OWN bm_catalog
    tree (family → product line → product), and those names ARE what
    clients say: "APX™ NEXT"/"aPXNext_BOM" lives only in the APX
    export, "SVX Video Remote Speaker Microphone"/"vX650_BOM" only in
    the SVX one (confirmed live, workspace 14). Unlike the flat
    productSelectionProduct_all menu — the identical full-portfolio
    list in every catalog, useless for discrimination — the tree is
    catalog-scoped, so a product/line name maps unambiguously to its
    family.

    Every alias (the family name itself, plus each bm_catalog entity's
    variable name and display name) maps to the family name detection
    should resolve to — the same value _scope_to_catalog matches back
    to one catalog when the config loads. An alias appearing under
    MORE THAN ONE family (a shared tree entry) is dropped entirely:
    ambiguous, never guess. Returns {} (never raises) when the reader
    can't answer — same contract as _ingested_product_names.
    """
    try:
        all_type_names = reader.distinct_types()
    except AttributeError:
        return {}
    prefixes = sorted({_engine_module._catalog_prefix(t) for t in all_type_names})
    alias_map: dict[str, str] = {}
    ambiguous: set[str] = set()
    for prefix in prefixes:
        fam_ents = reader.find_entities(
            ontology_type=f"{prefix}BmPrdFamily", limit=50)
        cat_ents = reader.find_entities(
            ontology_type=f"{prefix}BmCatalog", limit=200)
        if not fam_ents and not cat_ents:
            continue
        pg = engine._batch_fetch(
            [e["id"] for e in fam_ents + cat_ents], workspace_id)
        family_name = ""
        for fent in fam_ents:
            family_name = str(
                pg.get(fent["id"], {}).get("name") or fent.get("name") or ""
            ).strip()
            if family_name:
                break
        if not family_name:
            # No family entity in this export — the tree's root catalog
            # node (parent_id=-1) is the closest thing to a family name.
            for cent in cat_ents:
                a = pg.get(cent["id"], {})
                if str(a.get("parent_id") or "").strip() == "-1":
                    family_name = str(
                        a.get("name") or cent.get("name") or "").strip()
                    if family_name:
                        break
        if not family_name:
            continue
        aliases = {family_name}
        for cent in cat_ents:
            a = pg.get(cent["id"], {})
            for key in ("name", "bm_name"):
                nm = str(a.get(key) or "").strip()
                if nm:
                    aliases.add(nm)
        for nm in aliases:
            existing = alias_map.get(nm)
            if existing is not None and existing != family_name:
                ambiguous.add(nm)
            else:
                alias_map[nm] = family_name
    for nm in ambiguous:
        alias_map.pop(nm, None)
    return alias_map
