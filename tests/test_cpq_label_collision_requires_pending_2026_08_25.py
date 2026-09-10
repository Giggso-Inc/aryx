"""Regression coverage: `_label_collision_for` must not flag a same-labeled
sibling as a rival unless it's actually reachable as the next question.

Live-verified gap, 2026-08-25 (SVX Mounting Type): `mountType_viSoln` and
`mountingTypeArray_viSoln` share the display label "Mounting Type".
`mountType_viSoln` is unfilled but never actually in `pending` (excluded by
the ask-order/pending computation for reasons unrelated to its label).
Before this fix, `_label_collision_for` only checked "not yet filled",
so it still treated `mountType_viSoln` as a live rival and re-presented a
"which one did you mean?" prompt for an attribute the engine had already,
correctly, decided not to ask about. The fix adds a `pending` filter so
only a sibling the engine would actually ask next counts as a collision.
"""
from __future__ import annotations

from aryx.api.ask_label_collision.ask_label_collision_detect_and_compose import _label_collision_for
from aryx.cpq.state import ConfigAttr, CpqSession


def _mount() -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="mountType_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="single", options=[],
    )


def _mount_array() -> ConfigAttr:
    return ConfigAttr(
        entity_id=2, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi", options=[],
    )


def test_no_collision_when_sibling_is_unfilled_but_not_pending():
    """The exact SVX scenario: mountType_viSoln is unfilled but excluded
    from pending — must not be treated as a rival."""
    mount, mount_array = _mount(), _mount_array()
    attrs = [mount, mount_array]
    session = CpqSession(product_name="videoSolutions_BOM")
    pending = [mount_array]  # only the array attr is actually reachable next

    result = _label_collision_for(mount_array, attrs, session, pending)

    assert result is None


def test_collision_still_fires_when_both_siblings_are_pending():
    """Regression guard for the original bug this function fixed
    (2026-07-26, "Product" collision) — a genuine collision, where both
    same-labeled attrs are still pending together, must still trigger."""
    mount, mount_array = _mount(), _mount_array()
    attrs = [mount, mount_array]
    session = CpqSession(product_name="videoSolutions_BOM")
    pending = [mount_array, mount]  # both genuinely up for asking

    result = _label_collision_for(mount_array, attrs, session, pending)

    assert result is not None
    assert {a.variable_name for a in result} == {"mountType_viSoln", "mountingTypeArray_viSoln"}


def test_collision_check_is_backward_compatible_without_pending_arg():
    """Callers that don't pass `pending` (None) keep the pre-fix behavior
    — unfilled-anywhere-in-catalog still counts as a collision."""
    mount, mount_array = _mount(), _mount_array()
    attrs = [mount, mount_array]
    session = CpqSession(product_name="videoSolutions_BOM")

    result = _label_collision_for(mount_array, attrs, session)

    assert result is not None
    assert {a.variable_name for a in result} == {"mountType_viSoln", "mountingTypeArray_viSoln"}


def test_no_collision_once_one_sibling_is_already_filled():
    """Pre-existing behavior (2026-07-26 fix) must survive unchanged:
    once one same-labeled sibling is answered, the other is no longer a
    collision even if it happens to still be in pending."""
    mount, mount_array = _mount(), _mount_array()
    attrs = [mount, mount_array]
    session = CpqSession(product_name="videoSolutions_BOM")
    session.filled["mountType_viSoln"] = "Swivel Clip"
    pending = [mount_array]

    result = _label_collision_for(mount_array, attrs, session, pending)

    assert result is None
