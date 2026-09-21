"""``auto_fill``'s P4 post-pass: the hardware-before-product reorder
(Phase 4, the `auto_fill_resolve` decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md).

`_DECISION_REQUIRED_KEYS`, `_MAX_ENUMERATED_OPTIONS`, and
`_PRODUCT_LINE_SELECTOR_EXACT` are read off the engine MODULE object
(never patched by any test, but kept consistent with this file's own
`engine.<name>` convention for the two predicates that need `self`).

The one-sided "confirmed not applicable for this device" check itself
(`_hardware_version_confirmed_not_applicable`) lives on `CpqEngine` in
`engine.py`, not here — its own docstring explains why.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq import engine as _engine_module


def is_hardware_version_attr(attr: "Any") -> bool:
    """True for Hardware Version attrs (hWVersion_*, Hardware Version label).

    Hardware is mandatory on hardware-based product catalogs — used both
    to force always-ask and to order pending ahead of Product.
    """
    vn_flat = (attr.variable_name or "").lower().replace("_", "")
    label = (attr.display_label or "").lower()
    if "hwversion" in vn_flat or "hardwareversion" in vn_flat:
        return True
    if "hardware" in label and "version" in label:
        return True
    return False


def is_product_line_selector(attr: "Any") -> bool:
    """True for the shared multi-family Product dropdown (~325 options)."""
    vn = attr.variable_name or ""
    if vn in _engine_module._PRODUCT_LINE_SELECTOR_EXACT:
        return True
    vn_flat = vn.lower().replace("_", "")
    if "productselectionproduct" in vn_flat:
        return True
    label = (attr.display_label or "").strip().lower()
    if label == "product" and len(attr.options) > _engine_module._MAX_ENUMERATED_OPTIONS:
        return True
    return False


def is_svx_mounting_array_quantity_attr(attr: "Any") -> bool:
    """True for the SVX video-solutions catalog's per-option quantity
    attrs unlocked by a `mountingTypeArray_viSoln` selection (e.g.
    `mountingTypeShirtMagneticMountQuantity_viSoln`).

    Narrow, catalog-specific (not a general rule — see docs/
    CPQ_SVX_MOUNTING_TYPE_ASK_ORDER_PLAN_2026_08_24.md): live-confirmed
    these rank far behind the unrelated `mountType_viSoln` sibling
    attr in this catalog's own native layout order (order_number 95+
    vs. 6), so a customer who just picked a mount option gets asked
    about a completely different "Mounting Type" field before the
    quantity for their own just-made selection.
    """
    vn = attr.variable_name or ""
    return vn.startswith("mountingType") and vn.endswith("Quantity_viSoln")


def order_pending_hardware_before_product(
    engine: Any,
    pending: list["Any"],
    filled: dict[str, str],
    attrs: list["Any"],
    display_order: dict[str, int] | None = None,
    workspace_id: int | None = None,
    catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
    product_anchor_hint: str | None = None,
) -> list["Any"]:
    """Defer Product until Hardware is filled; sort pending by dependency.

    Live-confirmed (2026-07-28): after country was set, next prompt was
    Product with 325 options because productSelectionProduct_all is
    always-ask and catalog order listed it before Hardware. On
    hardware-based catalogs Hardware is mandatory and constrains Product
    — never ask the unconstrained product portfolio first.

    display_order — docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md §2b:
    when supplied, the real native UI's own sequence wins over the
    catalog-agnostic heuristic below (confirmed live to already agree
    with it on APX Next: Country → Hardware Version → Product). The
    Hardware-before-Product deferral itself is a correctness
    constraint (Product's options are genuinely unconstrained without
    it), not just an ordering preference, so it still applies first;
    display_order only changes the final sort key.

    workspace_id/catalog_prefix/cache/product_anchor_hint — same
    one-sided "confirmed not applicable for THIS specific device"
    override as auto_fill's is_decision_attr check (see
    CpqEngine._hardware_version_confirmed_not_applicable's own
    docstring); `None` (every default) keeps this function's existing
    behavior for every caller that doesn't pass them.
    """
    if not pending:
        return pending

    def _hw_forced(a: "Any") -> bool:
        return engine._is_hardware_version_attr(a) and not (
            engine._hardware_version_confirmed_not_applicable(
                product_anchor_hint, workspace_id, catalog_prefix, cache,
            )
        )

    if display_order is not None:
        # Deferral still applies (see docstring); ranking is layout
        # position, with anything absent from the map (shouldn't
        # happen once display_order-gated §2c is active, since
        # pending would only ever hold decision attrs/grid selectors —
        # both real layout members) sorted after everything ranked.
        catalog_has_hw = any(_hw_forced(a) for a in attrs)
        if catalog_has_hw:
            hw_vns = {a.variable_name for a in attrs if _hw_forced(a)}
            hw_filled = any(vn in filled and filled.get(vn) for vn in hw_vns)
            if not hw_filled:
                pending = [a for a in pending if not engine._is_product_line_selector(a)]
        return sorted(
            pending,
            key=lambda a: display_order.get(a.variable_name, 10**9),
        )

    catalog_has_hw = any(_hw_forced(a) for a in attrs)
    if not catalog_has_hw:
        # Non-hardware catalog (e.g. pure software): keep country first,
        # then original relative order.
        countryish = [
            a for a in pending
            if any(
                dk in a.variable_name.lower().replace("_", "")
                for dk in _engine_module._DECISION_REQUIRED_KEYS
            )
        ]
        rest = [a for a in pending if a not in countryish]
        return countryish + rest

    hw_vns = {a.variable_name for a in attrs if _hw_forced(a)}
    hw_filled = any(vn in filled and filled.get(vn) for vn in hw_vns)

    # Drop product-line selectors from pending until hardware is known.
    if not hw_filled:
        pending = [
            a for a in pending if not engine._is_product_line_selector(a)
        ]

    def _rank(a: "Any") -> tuple[int, int]:
        vn_flat = a.variable_name.lower().replace("_", "")
        if any(dk in vn_flat for dk in _engine_module._DECISION_REQUIRED_KEYS):
            return (0, a.order)
        if _hw_forced(a):
            return (1, a.order)
        if engine._is_product_line_selector(a):
            return (3, a.order)
        return (2, a.order)

    return sorted(pending, key=_rank)
