"""The two layout display-order maps -- visible-only (§2) and full (§2b) --
derived from a catalog's decoded native-UI layout export (Phase 4 step 5
extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Both call back onto ``CpqEngine._load_layout_components``, so each takes an
explicit ``engine`` first parameter. Their caches go through the engine
module object (tests reach for ``aryx.cpq.engine._LAYOUT_*_CACHE`` by dotted
path for per-test isolation).
"""

from __future__ import annotations

from aryx.cpq import engine as _engine_module
from aryx.cpq.layout_and_join_data.layout_variant import effective_variant
from aryx.cpq.layout_source import DEFAULT_LAYOUT_VARIANT, LayoutFileSource, layout_cache_key


def _components(engine, workspace_id, catalog_prefix, layout_source, variant):
    """Components for `variant`; the variant argument is only passed when
    non-sentinel, so the single-layout call shape is unchanged."""
    if variant == DEFAULT_LAYOUT_VARIANT:
        return engine._load_layout_components(workspace_id, catalog_prefix, layout_source)
    return engine._load_layout_components(
        workspace_id, catalog_prefix, layout_source, variant)


def load_layout_display_order(
    engine, workspace_id: int, catalog_prefix: str = "",
    layout_source: LayoutFileSource | None = None,
    variant: str = DEFAULT_LAYOUT_VARIANT,
) -> dict[str, int] | None:
    """docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md §2 — {variable_name:
    rank} for exactly the attributes a catalog's decoded native-UI
    layout export marks `hide: false` and non-`HTML`-typed, ranked by
    the file's own document order (§1: the authoritative flat order —
    `bm_layout_model.order_number` is only sibling-scoped).

    Returns None when no matching, currently-Active layout file exists
    for this catalog — callers must treat that as "no layout signal",
    never as "empty visible set" (every §2/§2b/§2c mechanism built on
    this falls back to today's unchanged behavior in that case).

    layout_source — injected for tests; defaults to the process-wide
    Oracle ADB / Postgres source (see LayoutFileSource).
    variant — which stored layout; with `cpq_layout_variants_enabled` on and
    the default passed, the variant is chosen from the bound model
    (layout_variant.effective_variant), else the single layout as before.
    """
    cache = _engine_module._LAYOUT_DISPLAY_ORDER_CACHE
    variant = effective_variant(workspace_id, catalog_prefix, variant, layout_source)
    key = layout_cache_key(workspace_id, catalog_prefix, variant)
    if key in cache:
        return cache[key]
    components = _components(engine, workspace_id, catalog_prefix, layout_source, variant)
    if components is None:
        cache[key] = None
        return None
    order: dict[str, int] = {}
    for comp in components:
        vn = comp.get("resourceAttributeVarName")
        if (
            vn and comp.get("hide") is False
            and comp.get("resourceAttrType") != "HTML"
            and vn not in order
        ):
            order[vn] = len(order)
    result = order or None
    cache[key] = result
    return result


def _load_layout_full_order(
    engine, workspace_id: int, catalog_prefix: str = "",
    layout_source: LayoutFileSource | None = None,
    variant: str = DEFAULT_LAYOUT_VARIANT,
) -> dict[str, int] | None:
    """docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md §2b — {variable_name:
    rank} over EVERY component in the layout file's document order,
    regardless of `hide`/`resourceAttrType` — used for rule-conflict
    ranking, where a rule's condition attribute is very often itself
    layout-hidden (a derived/computed attr, e.g. Base Model, is never
    shown to the customer but still gates other rules). Distinct from
    `load_layout_display_order`, which intentionally excludes exactly
    those hidden attrs for the summary/payload visible-set use case.
    """
    cache = _engine_module._LAYOUT_FULL_ORDER_CACHE
    variant = effective_variant(workspace_id, catalog_prefix, variant, layout_source)
    key = layout_cache_key(workspace_id, catalog_prefix, variant)
    if key in cache:
        return cache[key]
    components = _components(engine, workspace_id, catalog_prefix, layout_source, variant)
    if components is None:
        cache[key] = None
        return None
    order: dict[str, int] = {}
    for comp in components:
        vn = comp.get("resourceAttributeVarName")
        if vn and vn not in order:
            order[vn] = len(order)
    result = order or None
    cache[key] = result
    return result


def load_layout_hidden_vns(
    engine, workspace_id: int, catalog_prefix: str = "",
    layout_source: LayoutFileSource | None = None,
    variant: str = DEFAULT_LAYOUT_VARIANT,
) -> set[str] | None:
    """Variable names the catalog's native-UI layout export explicitly marks
    `hide: true` -- the attributes the real screen never shows.

    Distinct from "absent from `load_layout_display_order`": an attribute the
    layout does not place at all may simply be missing from an incomplete
    export, while `hide: true` is the layout stating it is hidden. Returns
    None when no matching, currently-Active layout file exists (no layout
    signal -- callers keep today's behaviour). The components are already
    cached per layout by `_load_layout_components`, so this adds one pass over
    a few hundred components.
    """
    variant = effective_variant(workspace_id, catalog_prefix, variant, layout_source)
    components = _components(engine, workspace_id, catalog_prefix, layout_source, variant)
    if components is None:
        return None
    hidden: set[str] = set()
    shown: set[str] = set()
    for comp in components:
        vn = comp.get("resourceAttributeVarName")
        if not vn:
            continue
        (hidden if comp.get("hide") is True else shown).add(vn)
    return hidden - shown    # placed twice, once visible: the screen shows it
