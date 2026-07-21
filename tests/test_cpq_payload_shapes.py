"""build_payload: shapes/inclusion rejected live by the real CPQ BOM API.

Live finding (workspace 14, real submission — docs/CPQ_PRODUCT_SWITCH_ISSUE.md
Issue 5): five SVX attrs came back "has an invalid payload". Root causes:

1. set_type=2 attrs (transient UI/action layer — the APX catalog's own
   population is _price_book_var_name / mergePackage / update /
   clearPackageJson / testPager2...) must be EXCLUDED from the payload,
   same as hide_in_trans. Values and wrapper shape were verified correct —
   inclusion itself was the defect.
2. A MENU-backed numeric (bWCNumberOfRefreshes_viSoln: data_type=3 but
   real menu items "1"/"2"/"3") was serialized as bare ``1``; the API
   expects the menu shape ``{"value","displayValue"}``. Menu presence wins
   over data_type.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=f"Display {v}", order=i)
            for i, v in enumerate(values, start=1)]


def _payload(attrs, filled, filled_multi=None):
    return CpqEngine().build_payload(
        filled, {k: "user" for k in filled}, filled_multi or {}, attrs,
    )["configData"]


def test_set_type_2_attr_is_excluded_from_payload():
    attrs = [
        ConfigAttr(entity_id=1, variable_name="modelSel", display_label="Select Model",
                   required=False, default_value="", options=_menu("A", "B"),
                   set_type="2"),
        ConfigAttr(entity_id=2, variable_name="country", display_label="Country",
                   required=False, default_value="", options=_menu("US"),
                   set_type="1"),
    ]
    out = _payload(attrs, {"modelSel": "A", "country": "US"})

    assert "modelSel" not in out, "set_type=2 (transient layer) must never be POSTed"
    assert out["country"] == {"value": "US", "displayValue": "Display US"}


def test_set_type_2_multi_attr_is_excluded_too():
    attrs = [ConfigAttr(entity_id=1, variable_name="multiSel", display_label="Multi",
                        required=False, default_value="", options=_menu("A", "B"),
                        select_type="multi", set_type="2")]
    out = _payload(attrs, {}, filled_multi={"multiSel": ["A", "B"]})

    assert "multiSel" not in out


def test_array_control_attr_derives_row_count_when_link_is_unambiguous():
    # docs/CPQ_SESSION_2_OPEN_ISSUES.md item 3, corrected: a genuine
    # reference payload confirmed mountingArrayControl_viSoln IS expected
    # in the real payload, as a bare int equal to the array-set's row
    # count — NOT excluded (the original fix's assumption was wrong; its
    # raw filled value is still disconnected/coincidental, but the
    # COUNT of selected rows is a real, derivable fact when there's
    # exactly one array-control attr and exactly one select_type=="multi"
    # attr to link it to, avoiding any name-matching guess).
    attrs = [
        ConfigAttr(entity_id=1, variable_name="mountingArrayControl_viSoln",
                   display_label="Mounting Array Control", required=False,
                   default_value="", options=_menu("5", "7"), is_array_control=True),
        ConfigAttr(entity_id=2, variable_name="mountingTypeArray_viSoln",
                   display_label="Mounting Type", required=False,
                   default_value="", options=_menu("Shirt Magnetic Mount", "Jacket Magnetic Mount"),
                   select_type="multi"),
    ]
    out = _payload(
        attrs,
        {"mountingArrayControl_viSoln": "5"},  # stale/disconnected raw value — must be ignored
        filled_multi={"mountingTypeArray_viSoln": ["Shirt Magnetic Mount", "Jacket Magnetic Mount"]},
    )

    assert out["mountingArrayControl_viSoln"] == 2, (
        "must derive the real row count (2 selected), not the stale raw value (5)"
    )


def test_array_control_attr_abstains_when_the_link_is_ambiguous():
    # No select_type=="multi" attr present to link to (or 2+ candidates) —
    # deriving a count would require guessing WHICH multi-select this
    # control attr belongs to, which this engine's design principle
    # forbids (same discipline as resolve_array_grid_links). Abstain
    # entirely rather than ship a wrong or coincidental number.
    attrs = [
        ConfigAttr(entity_id=1, variable_name="mountingArrayControl_viSoln",
                   display_label="Mounting Array Control", required=False,
                   default_value="", options=_menu("5", "7"), is_array_control=True),
        ConfigAttr(entity_id=2, variable_name="mountingTypeLockingMolleMountQuantity_viSoln",
                   display_label="Locking Molle Mount Quantity", required=False,
                   default_value="", options=[]),
    ]
    out = _payload(attrs, {
        "mountingArrayControl_viSoln": "5",
        "mountingTypeLockingMolleMountQuantity_viSoln": "7",
    })

    assert "mountingArrayControl_viSoln" not in out
    assert out["mountingTypeLockingMolleMountQuantity_viSoln"] == "7"


def test_menu_backed_integer_uses_menu_shape_not_bare_number():
    attrs = [ConfigAttr(entity_id=1, variable_name="numRefreshes", display_label="Refreshes",
                        required=False, default_value="", options=_menu("1", "2", "3"),
                        select_type="integer", set_type="1")]
    out = _payload(attrs, {"numRefreshes": "1"})

    assert out["numRefreshes"] == {"value": "1", "displayValue": "Display 1"}, (
        "a menu-backed numeric is a menu to the API — bare int was rejected live"
    )


def test_plain_integer_without_menu_stays_bare():
    attrs = [ConfigAttr(entity_id=1, variable_name="qty", display_label="Qty",
                        required=False, default_value="", options=[],
                        select_type="integer", set_type="1")]
    out = _payload(attrs, {"qty": "7"})

    assert out["qty"] == 7, "non-menu integers keep the live-accepted bare shape"


def test_set_type_1_and_3_menus_are_unchanged():
    attrs = [
        ConfigAttr(entity_id=1, variable_name="a1", display_label="A1",
                   required=False, default_value="", options=_menu("X"), set_type="1"),
        ConfigAttr(entity_id=2, variable_name="a3", display_label="A3",
                   required=False, default_value="", options=_menu("Y"), set_type="3"),
        ConfigAttr(entity_id=3, variable_name="a0", display_label="A0",
                   required=False, default_value="", options=_menu("Z"), set_type=""),
    ]
    out = _payload(attrs, {"a1": "X", "a3": "Y", "a0": "Z"})

    assert out["a1"]["value"] == "X"
    assert out["a3"]["value"] == "Y"
    assert out["a0"]["value"] == "Z"
