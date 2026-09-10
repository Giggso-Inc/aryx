"""Live-confirmed real BOM API rejection (2026-08-26/31, SVX Mounting Type
(Array), TAA model): `HTTP 400: Index 10 for Array Set
mountingTypeArrayset_viSoln is not Valid.`

Root cause: build_payload's array-set `_index` was computed as the
selected option's position within the selector's FULL raw catalog option
list (all 12 raw mounting options — 6 of which have no linked quantity
attr at all and can never actually be selected through this conversation
flow). "TEK-LOK Belt Mount" sits at raw catalog position 10 (after 5
other real mounts plus a run of never-askable decorative options like
"Magnetic Mount", "MOLLE Mount", "Double Molle Mounts", ...) — but the
real Array Set for this model only has 6 rows (matching the native UI's
own row count), so index 10 is out of range.

Fix: reindex against only the options resolve_array_grid_links could
structurally link to a real per-option quantity attr — the raw, never-
askable options never occupy a slot in the index space.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


# The real raw catalog option list (12 total) — 6 real, linkable mounts
# interleaved with 6 decorative options that have no quantity attr at all.
_ALL_TWELVE = [
    "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount",
    "Jacket Clip Mount", "Locking Molle Mount", "Magnetic Mount",
    "MOLLE Mount", "Double Molle Mounts", "KF Magnetic Mounts",
    "KF Molle Mounts", "TEK-LOK Belt Mount", "Belt Mount",
]
_SIX_LINKED = [
    "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount",
    "Jacket Clip Mount", "Locking Molle Mount", "TEK-LOK Belt Mount",
]


def _attrs():
    driver = ConfigAttr(
        entity_id=1, variable_name="mountingArrayControl_viSoln",
        display_label="Mounting Array Control", required=False, default_value="",
        options=[], is_array_control=True,
        array_set_id=100, array_set_role="driver",
        array_set_wrapper_key="_setmountingTypeArrayset_viSoln",
    )
    selector = ConfigAttr(
        entity_id=2, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi",
        options=_opt(*_ALL_TWELVE),
        array_set_id=100, array_set_role="member", array_col_order=1,
    )
    qty_attrs = [
        ConfigAttr(
            entity_id=10 + i,
            variable_name="mountingType" + nm.replace(" ", "").replace("-", "") + "Quantity_viSoln",
            display_label=f"mounting type {nm} Quantity",
            required=False, default_value="", options=[], hidden=True,
        )
        for i, nm in enumerate(_SIX_LINKED)
    ]
    return [driver, selector, *qty_attrs]


def _payload(attrs, filled, filled_multi):
    return CpqEngine().build_payload(
        filled, {k: "user" for k in filled}, filled_multi, attrs,
    )["configData"]


def test_index_excludes_raw_options_with_no_linked_quantity_attr():
    """TAA model: all 6 real mounts selected -- TEK-LOK Belt Mount (raw
    catalog position 10) must get array _index 5, the last slot among the
    6 genuinely linkable options, not 10."""
    attrs = _attrs()
    filled = {
        "mountingTypeShirtMagneticMountQuantity_viSoln": "7",
        "mountingTypeJacketMagneticMountQuantity_viSoln": "8",
        "mountingTypeShirtClipMountQuantity_viSoln": "1",
        "mountingTypeJacketClipMountQuantity_viSoln": "3",
        "mountingTypeLockingMolleMountQuantity_viSoln": "9",
        "mountingTypeTEKLOKBeltMountQuantity_viSoln": "4",
    }
    filled_multi = {"mountingTypeArray_viSoln": list(_SIX_LINKED)}
    out = _payload(attrs, filled, filled_multi)
    rows = out["_setmountingTypeArrayset_viSoln"]["items"]
    indices = [r["_index"] for r in rows]
    assert indices == [0, 1, 2, 3, 4, 5], (
        f"expected _index 0-5 (6 real linkable mounts), got: {indices!r} -- "
        f"an index >= 6 is out of range for this array set's real row count"
    )
    teklok_row = rows[-1]
    assert teklok_row["_index"] == 5


def test_index_stays_within_range_for_a_narrower_base_model_selection():
    """Base model: only 5 of the 6 linkable mounts are ever selected (no
    TEK-LOK) -- indices must still be 0-4, matching the base model's own
    5-row array set."""
    attrs = _attrs()
    base_five = _SIX_LINKED[:5]
    filled = {
        "mountingTypeShirtMagneticMountQuantity_viSoln": "3",
        "mountingTypeJacketMagneticMountQuantity_viSoln": "7",
        "mountingTypeShirtClipMountQuantity_viSoln": "9",
        "mountingTypeJacketClipMountQuantity_viSoln": "1",
        "mountingTypeLockingMolleMountQuantity_viSoln": "5",
    }
    filled_multi = {"mountingTypeArray_viSoln": list(base_five)}
    out = _payload(attrs, filled, filled_multi)
    rows = out["_setmountingTypeArrayset_viSoln"]["items"]
    indices = [r["_index"] for r in rows]
    assert indices == [0, 1, 2, 3, 4]
