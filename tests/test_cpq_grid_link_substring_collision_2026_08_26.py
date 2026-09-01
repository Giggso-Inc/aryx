"""Live-confirmed real BOM API rejection (2026-08-26, SVX Mounting Type
(Array)): "Index 6 for Array Set mountingTypeArrayset_viSoln is not
Valid.", "Index 10 ... not Valid.", "Index 11 ... not Valid." — three
phantom array-set rows the customer never actually selected.

Root cause: resolve_array_grid_links matches an option to its quantity
attr by normalized substring containment. Two DIFFERENT real catalog
options can share a common substring, and the shorter one's token is a
literal substring of the longer, more specific option's own quantity
attr name:

  - "MOLLE Mount" -> token "mollemount" -> substring of
    "mountingTypeLockingMolleMountQuantity_viSoln" (meant for the
    separate "Locking Molle Mount" option).
  - "Belt Mount" -> token "beltmount" -> substring of
    "mountingTypeTEKLOKBeltMountQuantity_viSoln" (meant for the separate
    "TEK-LOK Belt Mount" option).

Both options ended up linked to the SAME quantity attr, so once that
attr was answered, BOTH got synthesized as separate array-set rows with
the same quantity -- one of them a phantom the customer never picked,
rejected by the real BOM API as an invalid index.

Fix: process options longest-token-first and remove a quantity candidate
from the pool once claimed, so the longer/more-specific option's genuine
match wins its candidate before a shorter, coincidentally-overlapping
option ever gets a chance at it.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _real_svx_attrs():
    selector = ConfigAttr(
        entity_id=1, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi",
        options=_opt(
            "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount",
            "Jacket Clip Mount", "Locking Molle Mount", "MOLLE Mount",
            "TEK-LOK Belt Mount", "Belt Mount",
        ),
    )
    names_with_own_qty = [
        "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount",
        "Jacket Clip Mount", "Locking Molle Mount", "TEK-LOK Belt Mount",
    ]
    qty_attrs = [
        ConfigAttr(
            entity_id=10 + i, variable_name="mountingType" + nm.replace(" ", "").replace("-", "") + "Quantity_viSoln",
            display_label=f"mounting type {nm} Quantity",
            required=False, default_value="", options=[], hidden=True,
        )
        for i, nm in enumerate(names_with_own_qty)
    ]
    return [selector, *qty_attrs]


def test_shorter_substring_option_does_not_steal_a_longer_options_quantity_attr():
    attrs = _real_svx_attrs()
    links = CpqEngine.resolve_array_grid_links(attrs)
    item_map = links["mountingTypeArray_viSoln"]

    assert "locking molle mount" in item_map, "the real, specific option must still link"
    assert item_map["locking molle mount"] == "mountingTypeLockingMolleMountQuantity_viSoln"
    assert "molle mount" not in item_map, (
        "MOLLE Mount has no quantity attr of its own -- it must NOT steal "
        "Locking Molle Mount's, which would synthesize a phantom row"
    )

    assert "tekloklog belt mount".replace("log", "") in item_map or "tek-lok belt mount" in item_map
    assert item_map["tek-lok belt mount"] == "mountingTypeTEKLOKBeltMountQuantity_viSoln"
    assert "belt mount" not in item_map, (
        "Belt Mount has no quantity attr of its own -- it must NOT steal "
        "TEK-LOK Belt Mount's, which would synthesize a phantom row"
    )


def test_a_genuinely_separate_quantity_attr_still_links_correctly():
    """Sanity check the fix doesn't over-correct: when BOTH options
    really do have their own distinct quantity attrs, each links to its
    own, not to each other's."""
    selector = ConfigAttr(
        entity_id=1, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi",
        options=_opt("Locking Molle Mount", "MOLLE Mount"),
    )
    locking_qty = ConfigAttr(
        entity_id=2, variable_name="mountingTypeLockingMolleMountQuantity_viSoln",
        display_label="mounting type Locking Molle Mount Quantity",
        required=False, default_value="", options=[], hidden=True,
    )
    molle_qty = ConfigAttr(
        entity_id=3, variable_name="mountingTypeMolleMountOnlyQuantity_viSoln",
        display_label="mounting type MOLLE Mount Quantity",
        required=False, default_value="", options=[], hidden=True,
    )
    attrs = [selector, locking_qty, molle_qty]
    links = CpqEngine.resolve_array_grid_links(attrs)
    item_map = links["mountingTypeArray_viSoln"]

    assert item_map["locking molle mount"] == "mountingTypeLockingMolleMountQuantity_viSoln"
    assert item_map["molle mount"] == "mountingTypeMolleMountOnlyQuantity_viSoln"
