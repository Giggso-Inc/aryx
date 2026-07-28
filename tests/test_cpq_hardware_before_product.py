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


def test_country_extract_destination_country_phrase() -> None:
    eng = CpqEngine()
    hints = eng.extract_hints(
        'Order APX Next Radios for customer whose destination country is '
        'United States and customer name is "HOUSTON, CITY OF"',
    )
    assert hints.get("country")
    assert "united" in hints["country"].lower()
