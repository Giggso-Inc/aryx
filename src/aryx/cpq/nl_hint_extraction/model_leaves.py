"""bm_catalog leaf-model resolution (Phase 4 step 11 extraction from
``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

The two halves of "which model did the customer punch in through?":
`single_model_variable_name` when the catalog's own tree has exactly one
leaf, `model_variable_candidates` for the ambiguous 2+-leaf case the
former deliberately refuses to guess at. Same tree walk, opposite
answers -- kept together so the leaf definition can never drift.

`_batch_fetch` goes back through the passed-in `engine` instance.
"""

from __future__ import annotations

from typing import Any


def single_model_variable_name(
    engine: Any, reader: Any, workspace_id: int, catalog_prefix: str,
) -> str:
    """The catalog's model variable name — ONLY when its own bm_catalog
    tree has exactly one model leaf; "" otherwise (never guess).

    Recreates the punch-in model context BigMachines injects at runtime
    (the `_bm_model_*` attrs a user enters the configurator through) —
    data that never exists in an XML export. When the tree makes the
    model unambiguous (SVX: family videoSolutions_BOM → line mobile_BOM
    → single leaf vX650_BOM), Aryx can seed it; when several leaves
    exist (APX Next: aPXNext_BOM AND aPXN70_BOM), returns "" and the
    model context stays unfilled — the quote's identity travels in the
    product selection there instead (Issue 11,
    docs/CPQ_PRODUCT_SWITCH_ISSUE.md). A leaf = a bm_catalog node whose
    native id is never another node's parent_id.
    """
    if not catalog_prefix:
        return ""
    cat_ents = reader.find_entities(
        ontology_type=f"{catalog_prefix}BmCatalog", limit=200)
    if not cat_ents:
        return ""
    pg = engine._batch_fetch([e["id"] for e in cat_ents], workspace_id)
    nodes: list[tuple[str, str, str]] = []  # (native_id, parent_id, name)
    for cent in cat_ents:
        a = pg.get(cent["id"], {})
        native = str(a.get("id") or "").strip()
        parent = str(a.get("parent_id") or "").strip()
        name = str(a.get("name") or cent.get("name") or "").strip()
        if native and name:
            nodes.append((native, parent, name))
    parent_ids = {p for _n, p, _nm in nodes if p and p != "-1"}
    leaves = [nm for native, _p, nm in nodes if native not in parent_ids]
    return leaves[0] if len(leaves) == 1 else ""


def model_variable_candidates(
    engine: Any, reader: Any, workspace_id: int, catalog_prefix: str,
) -> list[str]:
    """Companion to single_model_variable_name: the full list of leaf
    model variable names when the tree has 2+ (the ambiguous case that
    function deliberately returns "" for, rather than guessing).

    Amendment 10 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): a
    catalog like CommandCentral Aware has several model leaves
    (commandCentralAware2024_BOM, commandCentralAware2026_BOM,
    commandCentralDEMS_BOM, ...) under one family — with no single
    unambiguous leaf, _bm_model_variable_name was never seeded at
    all, and no question ever asked which one was meant; the turn
    fell through to unrelated "Product" attrs instead, which don't
    represent this identity in this catalog's data at all.

    Returns [] when there are 0 or exactly 1 leaves (that case is
    single_model_variable_name's job), else the distinct, sorted leaf
    names for the caller to present as a disambiguation choice.
    """
    if not catalog_prefix:
        return []
    cat_ents = reader.find_entities(
        ontology_type=f"{catalog_prefix}BmCatalog", limit=200)
    if not cat_ents:
        return []
    pg = engine._batch_fetch([e["id"] for e in cat_ents], workspace_id)
    nodes: list[tuple[str, str, str]] = []
    for cent in cat_ents:
        a = pg.get(cent["id"], {})
        native = str(a.get("id") or "").strip()
        parent = str(a.get("parent_id") or "").strip()
        name = str(a.get("name") or cent.get("name") or "").strip()
        if native and name:
            nodes.append((native, parent, name))
    parent_ids = {p for _n, p, _nm in nodes if p and p != "-1"}
    leaves = sorted({nm for native, _p, nm in nodes if native not in parent_ids})
    return leaves if len(leaves) >= 2 else []
