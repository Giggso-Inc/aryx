"""Regression coverage: an optional multi-select's prompt tells the user
they can skip it.

ask_api.py already recognizes "skip"/"none"/"no...needed" as a valid
decline for an optional (required=False) multi-select reaching the
pending-question path (confirmed live: mountingTypeArray_viSoln correctly
resolves to an empty selection) — but the prompt itself never told the
user that option existed, so nobody would think to try it. An optional
multi-select reaching next_question_prompt at all is, by construction, a
grid selector (every OTHER optional multi-select is auto-filled empty
without ever being asked).
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def test_optional_multiselect_prompt_includes_skip_hint():
    attr = ConfigAttr(
        entity_id=1, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi",
        options=_menu("Shirt Magnetic Mount", "Jacket Magnetic Mount"),
    )
    prompt = CpqEngine().next_question_prompt(attr)
    assert "skip" in prompt.lower()
    assert "Mounting Type" in prompt


def test_required_multiselect_prompt_has_no_skip_hint():
    attr = ConfigAttr(
        entity_id=1, variable_name="requiredMulti_viSoln", display_label="Required Multi",
        required=True, default_value="", select_type="multi",
        options=_menu("A", "B"),
    )
    prompt = CpqEngine().next_question_prompt(attr)
    assert "skip" not in prompt.lower()


def test_single_select_prompt_has_no_skip_hint():
    attr = ConfigAttr(
        entity_id=1, variable_name="serviceType_viSoln", display_label="Service Type",
        required=False, default_value="", select_type="single",
        options=_menu("A", "B"),
    )
    prompt = CpqEngine().next_question_prompt(attr)
    assert "skip" not in prompt.lower()


def test_prompt_disambiguates_a_colliding_label_when_attrs_given():
    """Live incident 2026-08-21: mountType_viSoln and mountingTypeArray_
    viSoln both carry the literal display_label "Mounting Type".
    _label_collision_for (ask_api.py) deliberately excludes an already-
    ANSWERED sibling from its "which one did you mean" re-ask (correct --
    nothing left to disambiguate BETWEEN), but that left the remaining
    single pending attr's raw, still-colliding label on screen with no
    indication it's a different attribute from the one just answered
    under the identical text. `attrs` (opt-in, default None) lets the
    caller supply the full sibling list so the header uses
    disambiguated_label instead -- catalog-agnostic, no attribute name
    hardcoded in the fix itself (only in this test's fixture)."""
    mount_type = ConfigAttr(
        entity_id=1, variable_name="mountType_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="single",
        options=_menu("Swivel Clip and Adjustable Lanyard", "Swivel Clip"),
    )
    mounting_type_array = ConfigAttr(
        entity_id=2, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi",
        options=_menu("Shirt Magnetic Mount", "Jacket Magnetic Mount"),
    )
    attrs = [mount_type, mounting_type_array]
    engine = CpqEngine()

    # Without attrs (existing callers, unchanged): bare, colliding label.
    bare_prompt = engine.next_question_prompt(mount_type)
    assert bare_prompt.count("Mounting Type") >= 1
    assert "(" not in bare_prompt.split("—")[0]

    # With attrs supplied: the header disambiguates instead of repeating
    # the exact same text the sibling was just answered under.
    disambiguated_prompt = engine.next_question_prompt(mount_type, attrs=attrs)
    assert disambiguated_prompt.startswith("**Mounting Type (")
    assert "Swivel Clip and Adjustable Lanyard" in disambiguated_prompt

    # The sibling itself, when it's the one being asked, still shows its
    # own distinguishing fragment too -- neither side silently wins.
    sibling_prompt = engine.next_question_prompt(mounting_type_array, attrs=attrs)
    assert sibling_prompt.startswith("**Mounting Type (")
    assert disambiguated_prompt.split("\n")[0] != sibling_prompt.split("\n")[0]
