"""Explicit product decision (2026-08-25): instead of first asking the
customer to pick which mounting-type options they want (a "choose one:"
list), a grid-linked multi-select now asks the quantity for EVERY real
linked option directly, one at a time -- blank/"0" simply excludes that
option. This matches the native UI's own fixed per-option row grid more
literally, and sidesteps needing the customer to enumerate names at all.

Mechanism (generic, keyed only on resolve_array_grid_links -- no
attribute/catalog name hardcoded):
- resolve_pending_grid_quantities: when the selector has NO selection
  recorded at all yet, every real linked option's quantity attr is
  treated as pending (previously: only already-selected rows).
- append_pending_grid_quantities: the selector's own question is
  excluded from `pending` while its per-option quantities are still
  outstanding -- replaced entirely by the per-option flow.
- _finalize_grid_selections_from_quantities: once every linked option's
  quantity has been answered, the selector's own filled_multi entry is
  synthesized from the options that got a real, positive quantity.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i)
            for i, v in enumerate(values, start=1)]


def _grid_attrs() -> list[ConfigAttr]:
    selector = ConfigAttr(
        entity_id=1, variable_name="mountingTypeArray_viSoln",
        display_label="Mounting Type", required=False, default_value="",
        select_type="multi",
        options=_menu("Locking Molle Mount", "Jacket Magnetic Mount", "Shirt Magnetic Mount"),
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


def test_resolve_pending_grid_quantities_returns_every_option_when_unselected():
    eng = CpqEngine()
    attrs = _grid_attrs()

    extra = eng.resolve_pending_grid_quantities(attrs, {}, {})

    assert {a.variable_name for a in extra} == {
        "mountingTypeLockingMolleMountQuantity_viSoln",
        "mountingTypeJacketMagneticMountQuantity_viSoln",
        "mountingTypeShirtMagneticMountQuantity_viSoln",
    }


def test_resolve_pending_grid_quantities_reverts_to_selected_only_once_answered():
    """Backward-compat guard: once the selector DOES have a real
    selection (customer answered normally), only already-selected rows
    are asked -- the exact pre-existing behavior, unaffected."""
    eng = CpqEngine()
    attrs = _grid_attrs()
    filled_multi = {"mountingTypeArray_viSoln": ["Locking Molle Mount"]}

    extra = eng.resolve_pending_grid_quantities(attrs, {}, filled_multi)

    assert [a.variable_name for a in extra] == [
        "mountingTypeLockingMolleMountQuantity_viSoln",
    ]


def test_append_pending_grid_quantities_excludes_the_selector_own_question():
    eng = CpqEngine()
    attrs = _grid_attrs()
    selector = attrs[0]
    pending = [selector]

    result = eng.append_pending_grid_quantities(pending, attrs, {}, {})

    assert selector not in result, (
        "the selector's own 'choose one' question must be replaced by "
        "the per-option quantity questions, not asked redundantly"
    )
    assert {a.variable_name for a in result} == {
        "mountingTypeLockingMolleMountQuantity_viSoln",
        "mountingTypeJacketMagneticMountQuantity_viSoln",
        "mountingTypeShirtMagneticMountQuantity_viSoln",
    }


def test_finalize_synthesizes_selection_only_once_every_option_is_answered():
    eng = CpqEngine()
    attrs = _grid_attrs()
    filled_multi: dict[str, list[str]] = {}

    # Only 2 of 3 answered -- must NOT finalize yet.
    filled = {
        "mountingTypeLockingMolleMountQuantity_viSoln": "5",
        "mountingTypeJacketMagneticMountQuantity_viSoln": "0",
    }
    eng._finalize_grid_selections_from_quantities(attrs, filled, filled_multi)
    assert "mountingTypeArray_viSoln" not in filled_multi

    # Last one answered -- now finalizes.
    filled["mountingTypeShirtMagneticMountQuantity_viSoln"] = "3"
    eng._finalize_grid_selections_from_quantities(attrs, filled, filled_multi)

    assert filled_multi["mountingTypeArray_viSoln"] == [
        "Locking Molle Mount", "Shirt Magnetic Mount",
    ], "a '0' quantity must exclude that option; positive quantities include it"


def test_finalize_never_overrides_an_already_answered_selector():
    """A selector the customer already answered directly must be left
    completely untouched, even if all its quantity attrs happen to be
    filled -- never re-derives over a real customer choice."""
    eng = CpqEngine()
    attrs = _grid_attrs()
    filled_multi = {"mountingTypeArray_viSoln": ["Jacket Magnetic Mount"]}
    filled = {
        "mountingTypeLockingMolleMountQuantity_viSoln": "5",
        "mountingTypeJacketMagneticMountQuantity_viSoln": "10",
        "mountingTypeShirtMagneticMountQuantity_viSoln": "3",
    }

    eng._finalize_grid_selections_from_quantities(attrs, filled, filled_multi)

    assert filled_multi["mountingTypeArray_viSoln"] == ["Jacket Magnetic Mount"]


def test_full_turn_by_turn_cycle_asks_every_option_then_synthesizes():
    """End-to-end simulation of the new flow across multiple turns,
    driving the exact same functions append_pending_grid_quantities
    wraps -- one option answered per turn, selector never directly
    asked, filled_multi correctly synthesized at the end."""
    eng = CpqEngine()
    attrs = _grid_attrs()
    selector = attrs[0]
    filled: dict[str, str] = {}
    filled_multi: dict[str, list[str]] = {}

    # Turn 1: nothing answered yet -- selector excluded, all 3 qty pending.
    pending = eng.append_pending_grid_quantities([selector], attrs, filled, filled_multi)
    assert selector not in pending
    assert len(pending) == 3

    # Answer them one at a time, exactly like real turns would.
    filled["mountingTypeLockingMolleMountQuantity_viSoln"] = "5"
    pending = eng.append_pending_grid_quantities([selector], attrs, filled, filled_multi)
    assert selector not in pending
    assert {a.variable_name for a in pending} == {
        "mountingTypeJacketMagneticMountQuantity_viSoln",
        "mountingTypeShirtMagneticMountQuantity_viSoln",
    }

    filled["mountingTypeJacketMagneticMountQuantity_viSoln"] = "0"
    filled["mountingTypeShirtMagneticMountQuantity_viSoln"] = "8"
    # A real caller (auto_fill) only ever includes a GENUINELY unfilled
    # attr in `pending` to begin with -- it wouldn't hand the selector
    # back in once its own upstream fill-state check sees it's answered.
    # Mirror that here rather than forcing it back in unconditionally.
    seed_pending = [] if filled_multi.get(selector.variable_name) is not None else [selector]
    pending = eng.append_pending_grid_quantities(seed_pending, attrs, filled, filled_multi)

    assert filled_multi["mountingTypeArray_viSoln"] == [
        "Locking Molle Mount", "Shirt Magnetic Mount",
    ]
    assert selector not in pending, "finalized selector must never reappear in pending"
    assert not any(
        a.variable_name.endswith("Quantity_viSoln") for a in pending
    ), "every option answered -- no quantity attrs should remain pending"
