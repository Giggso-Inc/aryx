"""Optional multi-select (quantity-grid selector) explicit decline.

Live finding: after 1face2d made grid-linked selectors pend instead of
auto-emptying, a customer wanting NO rows was stuck — "no mounts needed"
was rejected as an invalid choice and the same question re-asked forever.
An explicit decline of an OPTIONAL (required="0") multi-select is a
settled answer: empty selection, question never re-asked, payload carries
no rows.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _multi(required: bool) -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="mountRows", display_label="Mounting Type",
        required=required, default_value="", select_type="multi",
        options=[
            MenuOption(item_value="Shirt Magnetic Mount", display_name="Shirt Magnetic Mount", order=1),
            MenuOption(item_value="Jacket Clip Mount", display_name="Jacket Clip Mount", order=2),
        ],
    )


def _qty_attr() -> ConfigAttr:
    """Hidden *Quantity*-named companion attr — resolve_array_grid_links'
    real matching mechanism (a >=6-alnum-char, single-match substring of
    an option's normalized text inside a hidden *Quantity* attr's
    normalized variable_name) — makes `mountRows` a REAL grid selector
    (docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_PLAN_2026_08_05.md
    follow-up: must be passed alongside `_multi()` in `attrs` for
    grid_selector_vns to actually classify it as one)."""
    return ConfigAttr(
        entity_id=2, variable_name="shirtMagneticMountQuantity_astro",
        display_label="Shirt Magnetic Mount Quantity",
        required=False, default_value="", select_type="single",
        options=[], hidden=True,
    )


def test_user_declined_empty_multi_stays_settled_in_auto_fill():
    engine = CpqEngine()
    attrs = [_multi(required=False)]
    filled_multi = {"mountRows": []}
    sources = {"mountRows": "user"}

    _f, display, pending = engine.auto_fill(
        attrs, hints={}, already_filled_multi=filled_multi, filled_source=sources)

    assert pending == [], "a user-declined optional grid must never re-pend"
    assert filled_multi == {"mountRows": []}, "the empty selection must survive"
    assert display.get("mountRows") == "(none)"


def test_constraint_dropped_empty_multi_still_reresolves():
    """Only USER-confirmed empties are settled — a constraint-drop that
    empties a selection (source != user) falls through to re-resolution.

    A REAL grid-linked selector (grid_selector_vns, confirmed via the
    hidden *Quantity* companion attr below) explicitly never gets
    auto-filled at all — not empty, not first-available — HITL-confirmed
    product decision (docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_PLAN_
    2026_08_05.md follow-up): picking an arbitrary accessory nobody asked
    for is worse than asking, so it falls through to `pending` instead."""
    engine = CpqEngine()
    attrs = [_multi(required=False), _qty_attr()]
    filled_multi = {"mountRows": []}
    sources = {"mountRows": "rule"}

    _filled, _display, pending = engine.auto_fill(
        attrs, hints={}, already_filled_multi=filled_multi, filled_source=sources)

    assert sources.get("mountRows") != "rule", (
        "non-user empty selections keep the pre-existing pop-and-reresolve path"
    )
    assert "mountRows" not in filled_multi, (
        "a real grid selector must never be auto-filled (empty or "
        "first-available) -- it falls through to pending instead"
    )
    assert [a.variable_name for a in pending] == ["mountRows"]


def test_declined_grid_ships_no_rows_in_payload():
    engine = CpqEngine()
    attrs = [_multi(required=False)]
    payload = engine.build_payload({}, {"mountRows": "user"}, {"mountRows": []}, attrs)
    data = payload[next(iter(payload))]

    assert "mountRows" not in data, "a declined grid contributes nothing to the payload"


# ── Post-completion change requests on multi-selects ────────────────────────
#
# Live finding: "I wanted to include the mounting type: Locking Molle Mount"
# after completing with a declined grid fell through to the review nudge —
# detect_change_request only consulted the scalar `filled` dict, so NO
# multi-select was ever eligible for a change.

def test_change_request_detected_on_declined_multi():
    engine = CpqEngine()
    attr = _multi(required=False)
    result = engine.detect_change_request(
        "I wanted to include the mounting type: Jacket Clip Mount",
        [attr], filled={}, filled_multi={"mountRows": []},
    )

    assert result is not None
    assert result[0].variable_name == "mountRows"


def test_change_request_detected_when_adding_a_new_row():
    engine = CpqEngine()
    attr = _multi(required=False)
    result = engine.detect_change_request(
        "add the Jacket Clip Mount too",
        [attr], filled={}, filled_multi={"mountRows": ["Shirt Magnetic Mount"]},
    )

    assert result is not None and result[0].variable_name == "mountRows"


def test_naming_an_already_selected_row_is_not_a_change():
    engine = CpqEngine()
    attr = _multi(required=False)
    result = engine.detect_change_request(
        "Shirt Magnetic Mount",
        [attr], filled={}, filled_multi={"mountRows": ["Shirt Magnetic Mount"]},
    )

    assert result is None


def test_multi_invisible_without_filled_multi_param():
    """Documents the pre-fix behavior the new param closes: without
    filled_multi, the attr isn't eligible at all."""
    engine = CpqEngine()
    attr = _multi(required=False)
    result = engine.detect_change_request(
        "I wanted to include the mounting type: Jacket Clip Mount",
        [attr], filled={},
    )

    assert result is None
