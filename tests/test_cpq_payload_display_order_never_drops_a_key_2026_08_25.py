"""build_payload's display_order step must never DROP a key — only rank it.

Live-verified gap, 2026-08-25 (SVX Mounting Type array-set payload): once a
catalog's native-UI layout export exists (aryx_cpq_layout_file, feeding
`display_order` via `load_layout_display_order`), `build_payload`'s
`display_order` step was a hard filter:

    ordered_keys = sorted((k for k in ordered_keys if k in display_order), ...)

A synthetic key this engine itself invents (e.g. an array-set driver's
`array_set_wrapper_key`, "_setmountingTypeArrayset_viSoln") can never
appear in a native layout export by construction — it doesn't correspond
to any single real BM attribute. Confirmed live: once SVX got its own
layout file, the customer's actual Mounting Type answer silently vanished
from the real submitted `configData` payload entirely, even though the
array-set row-building logic upstream still correctly held it right up
until this filter ran.

Fix: `display_order` now only RANKS known keys; any key absent from
`display_order` keeps its relative `ordered_keys` position and sorts
after every known key — the same "never lose a key" contract
`_dependency_ordered_keys` already guarantees for its own leftover/cycle
case.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=f"Display {v}", order=i)
            for i, v in enumerate(values, start=1)]


def _mounting_type_attrs():
    driver = ConfigAttr(
        entity_id=1, variable_name="mountingArrayControl_viSoln",
        display_label="Mounting Array Control", required=False, default_value="",
        options=[], is_array_control=True,
        array_set_id=100, array_set_role="driver",
        array_set_wrapper_key="_setmountingTypeArrayset_viSoln",
    )
    selector = ConfigAttr(
        entity_id=2, variable_name="mountingTypeArray_viSoln",
        display_label="Mounting Type", required=False, default_value="",
        options=_menu("Shirt Magnetic Mount", "Jacket Magnetic Mount"),
        select_type="multi",
        array_set_id=100, array_set_role="member", array_col_order=1,
    )
    return [driver, selector]


def test_synthetic_array_set_wrapper_key_survives_a_display_order_never_naming_it():
    """The exact SVX incident: a layout file exists (display_order is not
    None) but never names the synthetic wrapper key — it must still ship."""
    attrs = _mounting_type_attrs()
    out = CpqEngine().build_payload(
        {}, {"mountingTypeArray_viSoln": "user"},
        {"mountingTypeArray_viSoln": ["Shirt Magnetic Mount"]},
        attrs,
        display_order={},  # layout file loaded, but names nothing here
    )["configData"]

    assert "_setmountingTypeArrayset_viSoln" in out, (
        "a key absent from display_order must still ship, not be dropped"
    )
    assert out["_setmountingTypeArrayset_viSoln"]["items"] == [
        {"_index": 0},
    ]


def test_known_keys_still_rank_by_display_order_ahead_of_unknown_keys():
    attrs = _mounting_type_attrs()
    out = CpqEngine().build_payload(
        {"ultimateDestinationCountry": "US"},
        {"ultimateDestinationCountry": "user", "mountingTypeArray_viSoln": "user"},
        {"mountingTypeArray_viSoln": ["Shirt Magnetic Mount"]},
        attrs,
        display_order={"ultimateDestinationCountry": 0},
    )["configData"]

    keys = list(out.keys())
    assert keys.index("ultimateDestinationCountry") < keys.index("_setmountingTypeArrayset_viSoln"), (
        "a key present in display_order must still rank ahead of one absent from it"
    )


def test_display_order_none_is_unchanged_no_op():
    """Every existing caller not opting into a layout file at all must see
    zero behavior change."""
    attrs = _mounting_type_attrs()
    out = CpqEngine().build_payload(
        {}, {"mountingTypeArray_viSoln": "user"},
        {"mountingTypeArray_viSoln": ["Shirt Magnetic Mount"]},
        attrs,
    )["configData"]

    assert "_setmountingTypeArrayset_viSoln" in out
