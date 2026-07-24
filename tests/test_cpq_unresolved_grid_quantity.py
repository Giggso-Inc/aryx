"""Regression coverage for selected grid options with no resolvable
quantity attr (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 9).

Confirmed live (SVX, workspace 19): selecting both "Locking Molle Mount"
and the bare "Magnetic Mount" option only ever asked for ONE quantity
("mounting type Locking Molle Mount Quantity") — "Magnetic Mount"'s token
ambiguously matches BOTH "Jacket Magnetic Mount Quantity" and "Shirt
Magnetic Mount Quantity" (real catalog data has no dedicated quantity attr
for the bare option), so resolve_array_grid_links correctly never guesses
which one it means — but nothing surfaced this gap, and the flow declared
"Configuration complete" with a permanently-unaskable per-row quantity.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i)
            for i, v in enumerate(values, start=1)]


def _svx_shaped_attrs() -> list[ConfigAttr]:
    selector = ConfigAttr(
        entity_id=1, variable_name="mountingTypeArray_viSoln",
        display_label="Mounting Type", required=False, default_value="",
        select_type="multi",
        options=_menu("Locking Molle Mount", "Magnetic Mount",
                      "Jacket Magnetic Mount", "Shirt Magnetic Mount"),
    )
    locking_qty = ConfigAttr(
        entity_id=2, variable_name="mountingTypeLockingMolleMountQuantity_viSoln",
        display_label="mounting type Locking Molle Mount Quantity",
        required=False, default_value="", options=[], hidden=True,
    )
    jacket_qty = ConfigAttr(
        entity_id=3, variable_name="mountingTypeJacketMagneticMountQuantity_viSoln",
        display_label="mounting type Jacket Magnetic Mount Quantity",
        required=False, default_value="", options=[], hidden=True,
    )
    shirt_qty = ConfigAttr(
        entity_id=4, variable_name="mountingTypeShirtMagneticMountQuantity_viSoln",
        display_label="mounting type Shirt Magnetic Mount Quantity",
        required=False, default_value="", options=[], hidden=True,
    )
    return [selector, locking_qty, jacket_qty, shirt_qty]


def test_unresolved_grid_quantity_options_flags_the_ambiguous_bare_option():
    eng = CpqEngine()
    attrs = _svx_shaped_attrs()
    filled_multi = {"mountingTypeArray_viSoln": ["Locking Molle Mount", "Magnetic Mount"]}

    gaps = eng.unresolved_grid_quantity_options(attrs, filled_multi)

    assert gaps == [("Mounting Type", "Magnetic Mount")], (
        "the bare 'Magnetic Mount' option must be flagged — its token "
        "ambiguously matches both Jacket/Shirt Magnetic Mount Quantity"
    )


def test_unresolved_grid_quantity_options_empty_when_all_resolve():
    eng = CpqEngine()
    attrs = _svx_shaped_attrs()
    # Only the unambiguous option selected — no gap.
    filled_multi = {"mountingTypeArray_viSoln": ["Locking Molle Mount"]}

    gaps = eng.unresolved_grid_quantity_options(attrs, filled_multi)

    assert gaps == []


def test_unresolved_grid_quantity_options_empty_when_no_grid_mechanism_at_all():
    # A plain multi-select with no linked quantity attrs at all — this
    # function must not fire for ordinary multi-selects, only real grids.
    eng = CpqEngine()
    selector = ConfigAttr(
        entity_id=1, variable_name="plainMulti", display_label="Plain Multi",
        required=False, default_value="", select_type="multi",
        options=_menu("A", "B"),
    )
    gaps = eng.unresolved_grid_quantity_options([selector], {"plainMulti": ["A", "B"]})
    assert gaps == []


def test_resolve_pending_grid_quantities_still_asks_for_the_resolvable_one():
    # Regression guard: the existing mechanism for the RESOLVABLE selection
    # (Locking Molle Mount) must be completely unaffected by this addition.
    eng = CpqEngine()
    attrs = _svx_shaped_attrs()
    filled_multi = {"mountingTypeArray_viSoln": ["Locking Molle Mount", "Magnetic Mount"]}

    extra = eng.resolve_pending_grid_quantities(attrs, {}, filled_multi)

    assert len(extra) == 1
    assert extra[0].variable_name == "mountingTypeLockingMolleMountQuantity_viSoln"
