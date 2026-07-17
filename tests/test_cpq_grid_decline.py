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
    empties a selection (source != user) falls through to re-resolution,
    the pre-existing behavior."""
    engine = CpqEngine()
    attrs = [_multi(required=False)]
    filled_multi = {"mountRows": []}
    sources = {"mountRows": "rule"}

    engine.auto_fill(
        attrs, hints={}, already_filled_multi=filled_multi, filled_source=sources)

    assert sources.get("mountRows") != "rule", (
        "non-user empty selections keep the pre-existing pop-and-reresolve "
        "path (here: popped, then re-assigned by the optional-multi "
        "auto-empty with source 'default')"
    )
    assert sources.get("mountRows") == "default"


def test_declined_grid_ships_no_rows_in_payload():
    engine = CpqEngine()
    attrs = [_multi(required=False)]
    payload = engine.build_payload({}, {"mountRows": "user"}, {"mountRows": []}, attrs)
    data = payload[next(iter(payload))]

    assert "mountRows" not in data, "a declined grid contributes nothing to the payload"
