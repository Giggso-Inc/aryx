"""Hardware is mandatory before Product on hardware-based CPQ catalogs.

Regression for live transcript bug: after country was set, next prompt was
Product (325 options) instead of Hardware Version.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _attr(
    vn: str,
    label: str,
    *,
    order: int = 100,
    n_opts: int = 3,
    options: list[tuple[str, str]] | None = None,
) -> ConfigAttr:
    if options is None:
        options = [(f"v{i}", f"Opt {i}") for i in range(n_opts)]
    opts = [MenuOption(item_value=iv, display_name=dn, order=i) for i, (iv, dn) in enumerate(options)]
    return ConfigAttr(
        entity_id=hash(vn) % 100000,
        variable_name=vn,
        display_label=label,
        required=True,
        default_value="",
        options=opts,
        order=order,
    )


def test_hardware_detected_by_vn_and_label() -> None:
    eng = CpqEngine()
    assert eng._is_hardware_version_attr(
        _attr("hWVersion_astro", "Hardware Version"),
    )
    assert eng._is_hardware_version_attr(
        _attr("something_else", "Hardware Version"),
    )
    assert not eng._is_hardware_version_attr(
        _attr("productSelectionProduct_all", "Product"),
    )


def test_product_selector_detected() -> None:
    eng = CpqEngine()
    big = _attr(
        "productSelectionProduct_all", "Product",
        n_opts=50,
    )
    assert eng._is_product_line_selector(big)


def test_product_deferred_until_hardware_filled() -> None:
    eng = CpqEngine()
    hw = _attr("hWVersion_astro", "Hardware Version", order=50)
    product = _attr(
        "productSelectionProduct_all", "Product", order=10, n_opts=50,
    )
    country = _attr("ultimateDestinationCountry_astro", "Country", order=5)
    other = _attr("serviceType_astro", "Service Type", order=20)
    attrs = [product, hw, country, other]
    pending = [product, hw, country, other]

    ordered = eng._order_pending_hardware_before_product(pending, {}, attrs)
    # Product removed until hardware filled
    assert all(a.variable_name != "productSelectionProduct_all" for a in ordered)
    # Country first, then hardware
    assert ordered[0].variable_name == country.variable_name
    assert ordered[1].variable_name == hw.variable_name


def test_product_allowed_after_hardware_filled() -> None:
    eng = CpqEngine()
    hw = _attr("hWVersion_astro", "Hardware Version", order=50)
    product = _attr(
        "productSelectionProduct_all", "Product", order=10, n_opts=50,
    )
    attrs = [product, hw]
    pending = [product, hw]
    filled = {"hWVersion_astro": "H45TGU9PW8AN"}

    ordered = eng._order_pending_hardware_before_product(pending, filled, attrs)
    # Product is present and after hardware
    vns = [a.variable_name for a in ordered]
    assert "productSelectionProduct_all" in vns
    assert vns.index("hWVersion_astro") < vns.index("productSelectionProduct_all")


def test_non_hardware_catalog_keeps_product() -> None:
    eng = CpqEngine()
    product = _attr(
        "productSelectionProduct_all", "Product", order=10, n_opts=50,
    )
    service = _attr("serviceType_x", "Service", order=20)
    attrs = [product, service]
    ordered = eng._order_pending_hardware_before_product(
        [product, service], {}, attrs,
    )
    assert any(a.variable_name == "productSelectionProduct_all" for a in ordered)


# ── SVX mounting-type quantity queue-jump (2026-08-24) ───────────────────
#
# Live-confirmed bug: after selecting "Shirt Magnetic Mount" for
# mountingTypeArray_viSoln, every `resolve_pending_grid_quantities` append
# site in ask_api.py appended the just-unlocked
# mountingTypeShirtMagneticMountQuantity_viSoln attr to the END of
# `pending`, landing it behind the unrelated mountType_viSoln sibling --
# the customer got asked about a completely different "Mounting Type"
# field before the quantity for their own just-made selection. Fixed by
# extracting a single shared `CpqEngine.append_pending_grid_quantities`
# helper (replacing 7 duplicated append loops in ask_api.py) with the
# queue-jump built in. `_is_svx_mounting_array_quantity_attr` (narrow,
# catalog-scoped, not a general rule) is the classifier it keys on.

def test_is_svx_mounting_array_quantity_attr_classifier() -> None:
    eng = CpqEngine()
    assert eng._is_svx_mounting_array_quantity_attr(
        _attr("mountingTypeShirtMagneticMountQuantity_viSoln", "Shirt Magnetic Mount Quantity"),
    )
    assert eng._is_svx_mounting_array_quantity_attr(
        _attr("mountingTypeJacketMagneticMountQuantity_viSoln", "Jacket Magnetic Mount Quantity"),
    )
    assert not eng._is_svx_mounting_array_quantity_attr(
        _attr("mountType_viSoln", "Mounting Type"),
    )
    assert not eng._is_svx_mounting_array_quantity_attr(
        _attr("someOtherQuantity_astro", "Some Other Quantity"),
    )


def _svx_mounting_fixture():
    """A minimal, realistic slice of the real SVX catalog shape: a
    multi-select mounting-array selector with a hidden per-option quantity
    attr resolve_array_grid_links can link (>=6 alnum chars, exactly one
    candidate match — see that method's own docstring), plus the unrelated
    mountType_viSoln sibling already in `pending`."""
    mount_type = _attr("mountType_viSoln", "Mounting Type", order=6)
    array_selector = _attr(
        "mountingTypeArray_viSoln", "Mounting Type (Array)", order=90,
        options=[("Shirt Magnetic Mount", "Shirt Magnetic Mount")],
    )
    quantity = ConfigAttr(
        entity_id=999001, variable_name="mountingTypeShirtMagneticMountQuantity_viSoln",
        display_label="Shirt Magnetic Mount Quantity", required=False, default_value="",
        options=[], order=95, hidden=True,
    )
    attrs = [mount_type, array_selector, quantity]
    filled_multi = {"mountingTypeArray_viSoln": ["Shirt Magnetic Mount"]}
    return mount_type, array_selector, quantity, attrs, filled_multi


def test_svx_mounting_quantity_inserted_ahead_of_mount_type_via_real_helper() -> None:
    """End-to-end through the real `append_pending_grid_quantities` (which
    itself calls the real `resolve_array_grid_links`/
    `resolve_pending_grid_quantities`) -- not a re-implementation of the
    fix's logic."""
    eng = CpqEngine()
    mount_type, array_selector, quantity, attrs, filled_multi = _svx_mounting_fixture()
    solution_set = _attr("accessoriesSolutionSet_viSoln", "Solution Set", order=50)
    pending = [mount_type, solution_set]

    result = eng.append_pending_grid_quantities(pending, attrs, {}, filled_multi)

    vns = [a.variable_name for a in result]
    assert vns == [
        "mountingTypeShirtMagneticMountQuantity_viSoln", "mountType_viSoln",
        "accessoriesSolutionSet_viSoln",
    ], "the just-unlocked quantity attr must jump ahead of the unrelated mountType_viSoln"


def test_svx_mounting_quantity_appends_normally_without_mount_type_pending() -> None:
    """Regression safety: when mountType_viSoln isn't in `pending` at all
    (every other catalog), the quantity attr keeps the plain
    append-to-end behavior — this fix never changes ordering elsewhere."""
    eng = CpqEngine()
    _mount_type, array_selector, quantity, attrs, filled_multi = _svx_mounting_fixture()
    solution_set = _attr("accessoriesSolutionSet_viSoln", "Solution Set", order=50)
    pending = [solution_set]  # mountType_viSoln deliberately NOT pending

    result = eng.append_pending_grid_quantities(pending, attrs, {}, filled_multi)

    assert [a.variable_name for a in result] == [
        "accessoriesSolutionSet_viSoln", "mountingTypeShirtMagneticMountQuantity_viSoln",
    ]


def test_svx_mounting_quantity_not_re_added_once_already_answered() -> None:
    """Regression safety: once the quantity is actually filled, it must
    not be re-inserted (mirrors resolve_pending_grid_quantities' own
    `qty_vn in filled` skip)."""
    eng = CpqEngine()
    mount_type, _array_selector, _quantity, attrs, filled_multi = _svx_mounting_fixture()
    pending = [mount_type]
    filled = {"mountingTypeShirtMagneticMountQuantity_viSoln": "88"}

    result = eng.append_pending_grid_quantities(pending, attrs, filled, filled_multi)

    assert [a.variable_name for a in result] == ["mountType_viSoln"]


def test_country_extract_destination_country_phrase() -> None:
    eng = CpqEngine()
    hints = eng.extract_hints(
        'Order APX Next Radios for customer whose destination country is '
        'United States and customer name is "HOUSTON, CITY OF"',
    )
    assert hints.get("country")
    assert "united" in hints["country"].lower()
