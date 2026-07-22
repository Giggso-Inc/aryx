"""Regression coverage: "change both the mounting types quantity to 67"
sets every already-selected grid row's quantity attr to one value at once,
rather than being misread as a single-attribute value change against the
grid selector itself (67 is never a real mount option) or forcing an
unresolvable label-collision prompt against an unrelated single-select
sibling that shares the same display_label but has no quantity links at
all.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _mount_attrs() -> list[ConfigAttr]:
    selector = ConfigAttr(
        entity_id=1, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi",
        options=_menu("Shirt Magnetic Mount", "Jacket Magnetic Mount"),
    )
    single_sibling = ConfigAttr(
        entity_id=2, variable_name="mountType_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="single",
        options=_menu("Swivel Clip", "Adjustable Lanyard"),
    )
    shirt_qty = ConfigAttr(
        entity_id=3, variable_name="mountingTypeShirtMagneticMountQuantity_viSoln",
        display_label="mounting type Shirt Magnetic Mount Quantity",
        required=False, default_value="", select_type="single", options=[], hidden=True,
    )
    jacket_qty = ConfigAttr(
        entity_id=4, variable_name="mountingTypeJacketMagneticMountQuantity_viSoln",
        display_label="mounting type Jacket Magnetic Mount Quantity",
        required=False, default_value="", select_type="single", options=[], hidden=True,
    )
    return [selector, single_sibling, shirt_qty, jacket_qty]


def test_bulk_quantity_change_detected_for_both_selected_rows():
    eng = CpqEngine()
    attrs = _mount_attrs()
    filled_multi = {"mountingTypeArray_viSoln": ["Shirt Magnetic Mount", "Jacket Magnetic Mount"]}
    result = eng.detect_bulk_quantity_change(
        "change both the mounting types quantity to 67", attrs, filled_multi)
    assert result is not None
    selector_vn, item_values, new_qty = result
    assert selector_vn == "mountingTypeArray_viSoln"
    assert set(item_values) == {"Shirt Magnetic Mount", "Jacket Magnetic Mount"}
    assert new_qty == "67"


def test_bulk_quantity_change_none_without_quantity_keyword():
    eng = CpqEngine()
    attrs = _mount_attrs()
    filled_multi = {"mountingTypeArray_viSoln": ["Shirt Magnetic Mount", "Jacket Magnetic Mount"]}
    result = eng.detect_bulk_quantity_change(
        "change the mounting type to something else", attrs, filled_multi)
    assert result is None


def test_bulk_quantity_change_none_when_nothing_selected():
    eng = CpqEngine()
    attrs = _mount_attrs()
    result = eng.detect_bulk_quantity_change(
        "change both the mounting types quantity to 67", attrs, {})
    assert result is None


def test_bulk_quantity_change_never_targets_single_select_sibling():
    # mountType_viSoln shares the "Mounting Type" label but is select_type
    # "single" and has no grid-quantity links at all — must never be
    # returned as the bulk-quantity target, and must never force a
    # disambiguation prompt against it either (the caller only ever sees
    # this function's single unambiguous match).
    eng = CpqEngine()
    attrs = _mount_attrs()
    filled_multi = {"mountingTypeArray_viSoln": ["Shirt Magnetic Mount", "Jacket Magnetic Mount"]}
    selector_vn, _item_values, _new_qty = eng.detect_bulk_quantity_change(
        "change both the mounting types quantity to 67", attrs, filled_multi)
    assert selector_vn == "mountingTypeArray_viSoln"
    assert selector_vn != "mountType_viSoln"


def test_bulk_quantity_change_only_updates_actually_resolvable_rows():
    eng = CpqEngine()
    attrs = _mount_attrs()
    # "Locking Molle Mount" has no matching hidden quantity attr in this
    # fixture — only the resolvable Shirt/Jacket rows should come back.
    filled_multi = {
        "mountingTypeArray_viSoln": [
            "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Locking Molle Mount",
        ],
    }
    result = eng.detect_bulk_quantity_change(
        "set both mounting types quantity to 10", attrs, filled_multi)
    assert result is not None
    _selector_vn, item_values, _new_qty = result
    assert set(item_values) == {"Shirt Magnetic Mount", "Jacket Magnetic Mount"}
