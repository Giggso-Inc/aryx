"""Classification of filled attrs into the fixed, scannable summary
sections (Phase 4 step 10 extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

`_summary_category` is the per-attr, variable_name-fragment classifier;
`categorized_summary_groups` is its grouped, display-ordered consumer.

The category tables (`_SUMMARY_CATEGORY_KEYS`,
`_SUMMARY_FALLBACK_CATEGORY`, `_SUMMARY_MANDATORY_CATEGORY`) are read
off the engine MODULE object rather than imported by value, so the
original bare-global references -- and any patch of them -- resolve at
call time exactly as before. `_filled_summary_triples` /
`_summary_category` are likewise reached back through the passed-in
`engine` instance so their class-attribute lookups still apply.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aryx.cpq import engine as _engine_module

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aryx.cpq.state import ConfigAttr


def _summary_category(variable_name: str) -> str:
    """Classify a filled attr into one of the 5 scannable summary
    sections, purely by variable_name fragment — never a literal
    per-catalog field name, so it applies to any ingested XML the same
    way. See _SUMMARY_CATEGORY_KEYS docstring for the matching order.
    """
    vn_flat = (variable_name or "").lower().replace("_", "")
    for category, fragments in _engine_module._SUMMARY_CATEGORY_KEYS:
        if any(frag in vn_flat for frag in fragments):
            return category
    return _engine_module._SUMMARY_FALLBACK_CATEGORY


def categorized_summary_groups(
    engine: Any,
    display_filled: dict[str, str],
    attrs: list["ConfigAttr"] | None = None,
    rule_governed_ids: set[int] | None = None,
    sources: dict[str, str] | None = None,
    display_order: dict[str, int] | None = None,
    product_quantity: int | None = None,
    required_vns: frozenset[str] | None = None,
    product_anchor_hint: str | None = None,
    workspace_id: int | None = None,
    catalog_prefix: str = "",
    dt_cache: dict[tuple[int, str], tuple] | None = None,
) -> list[tuple[str, list[tuple[str, str]]]]:
    """(category, [(label, value), ...]) groups, non-empty categories
    only, in the fixed display order (Product Name, Service Plan,
    Quantity & Duration, then Mandatory User Input — narrowed scope,
    rule_governed_ids supplied — or Associated Options — full-detail-
    dump scope, rule_governed_ids=None — see _SUMMARY_CATEGORY_KEYS /
    _SUMMARY_MANDATORY_CATEGORY). Same filtering and classification
    `render_filled_summary` uses for its bullet output; exposed
    separately so callers that build their own presentation (e.g.
    ask_api's LLM-narrated summary) can group the same facts the same
    way instead of inventing their own grouping.

    In the narrowed scope, `_filled_summary_triples` already restricts
    its whole item list to exactly `_is_mandatory_input_attr`'s Tier
    A/B/C set (PR #222) — an item that doesn't match Product Name/
    Service Plan/Quantity & Duration's fragments is renamed from the
    old catch-all name to Mandatory User Input here (live-confirmed
    gap, 2026-08-19: it used to keep the old "Associated Options" name
    and get narrated as one vague, intentionally-partial line instead
    of being reliably, fully listed). The full-detail-dump scope is
    NOT narrowed to mandatory-only and keeps the original catch-all
    name/semantics unchanged.

    display_order — see `_filled_summary_triples`; restricts to and
    orders WITHIN each of the fixed categories above by layout rank
    when supplied. Does not replace the 4-category grouping itself.

    product_quantity — the session-level order quantity (a virtual
    fact, not a real catalog attribute, so it can never come out of
    `_filled_summary_triples`). Injected here as the FIRST fact under
    Product Name, labeled "Product Quantity" — previously appended as
    a hardcoded suffix after every category regardless of catalog
    shape, which always put it last (live-verified gap, 2026-08-13).
    Only injected when there's an actual configuration to attach it
    to (`triples` non-empty) — never synthesizes a Product Name
    section out of nothing when no product has been selected yet.

    required_vns — optional (default `None`); forwarded to
    `_filled_summary_triples` for Tier C (see `mandatory_tier_c_vns`).

    product_anchor_hint/workspace_id/catalog_prefix/dt_cache — docs/
    CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T3 (all default `None`/
    ``""``, no-op for every existing caller); forwarded to
    `_filled_summary_triples` for the Hardware Version applicability
    check.
    """
    triples = engine._filled_summary_triples(
        display_filled, attrs, rule_governed_ids, sources, display_order,
        required_vns=required_vns,
        product_anchor_hint=product_anchor_hint, workspace_id=workspace_id,
        catalog_prefix=catalog_prefix, dt_cache=dt_cache,
    )
    if not triples:
        return []
    by_category: dict[str, list[tuple[str, str]]] = {}
    for var, label, value in triples:
        category = engine._summary_category(var)
        # Narrowed scope (rule_governed_ids supplied): `triples` above
        # is already exactly the Mandatory User Input set (Tier A/B/C,
        # PR #222) -- an item landing in the old catch-all here is
        # mandatory by construction, so it's renamed rather than
        # re-classified. Full-detail-dump scope (rule_governed_ids=
        # None) is NOT narrowed to mandatory-only and keeps the
        # original catch-all name/semantics unchanged.
        if (category == _engine_module._SUMMARY_FALLBACK_CATEGORY
                and rule_governed_ids is not None):
            category = _engine_module._SUMMARY_MANDATORY_CATEGORY
        by_category.setdefault(category, []).append((label, value))
    if product_quantity is not None:
        by_category.setdefault("Product Name", [])
        by_category["Product Name"] = [
            ("Product Quantity", str(product_quantity)),
            *by_category["Product Name"],
        ]
    section_order = [c for c, _ in _engine_module._SUMMARY_CATEGORY_KEYS] + [
        _engine_module._SUMMARY_MANDATORY_CATEGORY,
        _engine_module._SUMMARY_FALLBACK_CATEGORY,
    ]
    return [
        (category, by_category[category])
        for category in section_order
        if by_category.get(category)
    ]
