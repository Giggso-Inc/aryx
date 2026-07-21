"""build_payload: BigMachines composite "array set" grouping
(docs/CPQ_ARRAY_SET_PAYLOAD_PLAN.md).

An array set (e.g. SVX's Mounting Type: mountingArrayControl_viSoln driver +
mountingTypeArray_viSoln/mountingTypeArrayqty_viSoln members) must serialize
as one _index-keyed row per selection under a single wrapper key, with the
driver shipping as a separate sibling row-count int — not the prior flat
per-column {"items":[{"value","displayValue"}]} shape.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=f"Display {v}", order=i)
            for i, v in enumerate(values, start=1)]


def _payload(attrs, filled=None, filled_multi=None):
    return CpqEngine().build_payload(
        filled or {}, {k: "user" for k in (filled or {})}, filled_multi or {}, attrs,
    )["configData"]


def _mounting_type_attrs(dummy_hidden=True):
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
    qty = ConfigAttr(
        entity_id=3, variable_name="mountingTypeArrayqty_viSoln",
        display_label="Quantity", required=False, default_value="",
        options=[], select_type="multi",
        array_set_id=100, array_set_role="member", array_col_order=2,
    )
    dummy = ConfigAttr(
        entity_id=4, variable_name="MountingQuantityDummyArrayAttribute_viSoln",
        display_label="Mounting Quantity Dummy Array Attribute",
        required=False, default_value="false", options=[], select_type="multi",
        hidden=dummy_hidden,
        array_set_id=100, array_set_role="member", array_col_order=3,
    )
    return [driver, selector, qty, dummy]


def test_array_set_member_groups_into_indexed_rows_not_flat_items():
    attrs = _mounting_type_attrs()
    out = _payload(attrs, filled_multi={
        "mountingTypeArray_viSoln": ["Shirt Magnetic Mount", "Jacket Magnetic Mount"],
        "mountingTypeArrayqty_viSoln": ["10", "10"],
    })

    assert "mountingTypeArray_viSoln" not in out, "must not ALSO appear flat"
    assert "mountingTypeArrayqty_viSoln" not in out
    wrapper = out["_setmountingTypeArrayset_viSoln"]
    assert wrapper["items"] == [
        {
            "_index": 0,
            "mountingTypeArray_viSoln": {"value": "Shirt Magnetic Mount", "displayValue": "Display Shirt Magnetic Mount"},
            "mountingTypeArrayqty_viSoln": 10,
        },
        {
            "_index": 1,
            "mountingTypeArray_viSoln": {"value": "Jacket Magnetic Mount", "displayValue": "Display Jacket Magnetic Mount"},
            "mountingTypeArrayqty_viSoln": 10,
        },
    ]


def test_non_array_set_multi_select_still_serializes_flat():
    attr = ConfigAttr(
        entity_id=1, variable_name="plainMulti", display_label="Plain Multi",
        required=False, default_value="", options=_menu("A", "B"), select_type="multi",
    )
    out = _payload([attr], filled_multi={"plainMulti": ["A", "B"]})

    assert out["plainMulti"] == {"items": [
        {"value": "A", "displayValue": "Display A"},
        {"value": "B", "displayValue": "Display B"},
    ]}


def test_array_set_driver_ships_as_sibling_row_count_not_nested_or_duplicated():
    attrs = _mounting_type_attrs()
    out = _payload(attrs, filled_multi={
        "mountingTypeArray_viSoln": ["Shirt Magnetic Mount", "Jacket Magnetic Mount"],
        "mountingTypeArrayqty_viSoln": ["10", "10"],
    })

    assert out["mountingArrayControl_viSoln"] == 2, "bare int row count, sibling key"
    wrapper = out["_setmountingTypeArrayset_viSoln"]
    for row in wrapper["items"]:
        assert "mountingArrayControl_viSoln" not in row, (
            "driver must not be duplicated inside member rows"
        )


def test_array_set_dummy_placeholder_member_excluded_from_rows():
    attrs = _mounting_type_attrs(dummy_hidden=True)
    out = _payload(attrs, filled_multi={
        "mountingTypeArray_viSoln": ["Shirt Magnetic Mount"],
        "mountingTypeArrayqty_viSoln": ["10"],
        "MountingQuantityDummyArrayAttribute_viSoln": ["false"],
    })

    wrapper = out["_setmountingTypeArrayset_viSoln"]
    assert len(wrapper["items"]) == 1
    assert "MountingQuantityDummyArrayAttribute_viSoln" not in wrapper["items"][0], (
        "hidden=1 dummy/placeholder member must never appear in a row"
    )
    assert "MountingQuantityDummyArrayAttribute_viSoln" not in out, (
        "dummy member must not leak as its own flat top-level key either"
    )


def test_array_set_with_no_selections_emits_nothing():
    attrs = _mounting_type_attrs()
    out = _payload(attrs, filled_multi={})

    assert "_setmountingTypeArrayset_viSoln" not in out
    assert "mountingArrayControl_viSoln" not in out
