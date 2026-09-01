"""Regression coverage: deselecting an option from an already-selected
multi-select ("remove Jacket Magnetic Mount" after both Shirt and Jacket
were selected).

Confirmed live: apply_multi_answer/_handle_cascade's multi-select branch
only ever UNIONS mentioned options with the current selection (the "also
include X" add case) — there was no removal path at all, so "remove
Jacket Magnetic Mount" fell straight through to "I didn't quite catch
that" with both mounts still selected.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _mount_attr() -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi",
        options=_menu("Shirt Magnetic Mount", "Jacket Magnetic Mount", "Locking Molle Mount"),
    )


def test_removal_detected_for_a_currently_selected_option():
    eng = CpqEngine()
    attr = _mount_attr()
    filled_multi = {"mountingTypeArray_viSoln": ["Shirt Magnetic Mount", "Jacket Magnetic Mount"]}
    result = eng.detect_multi_select_removal("remove Jacket Magnetic Mount", [attr], filled_multi)
    assert result is not None
    matched_attr, to_remove = result
    assert matched_attr.variable_name == "mountingTypeArray_viSoln"
    assert to_remove == ["Jacket Magnetic Mount"]


def test_removal_ignored_when_verb_present_but_option_not_currently_selected():
    # "remove Locking Molle Mount" when it was never selected in the first
    # place isn't a real removal — must not silently do anything.
    eng = CpqEngine()
    attr = _mount_attr()
    filled_multi = {"mountingTypeArray_viSoln": ["Shirt Magnetic Mount", "Jacket Magnetic Mount"]}
    result = eng.detect_multi_select_removal("remove Locking Molle Mount", [attr], filled_multi)
    assert result is None


def test_removal_not_detected_without_a_removal_verb():
    # "also include Locking Molle Mount" is an ADD, not a removal — must
    # stay on the existing apply_multi_answer/_handle_cascade add path,
    # completely unaffected by this new detector.
    eng = CpqEngine()
    attr = _mount_attr()
    filled_multi = {"mountingTypeArray_viSoln": ["Shirt Magnetic Mount", "Jacket Magnetic Mount"]}
    result = eng.detect_multi_select_removal(
        "also include Locking Molle Mount", [attr], filled_multi)
    assert result is None


def test_removal_none_when_nothing_currently_selected():
    eng = CpqEngine()
    attr = _mount_attr()
    result = eng.detect_multi_select_removal("remove Jacket Magnetic Mount", [attr], {})
    assert result is None


def test_removal_recognizes_alternate_verbs():
    eng = CpqEngine()
    attr = _mount_attr()
    filled_multi = {"mountingTypeArray_viSoln": ["Shirt Magnetic Mount", "Jacket Magnetic Mount"]}
    for phrase in (
        "deselect Jacket Magnetic Mount",
        "delete Jacket Magnetic Mount",
        "take out Jacket Magnetic Mount",
        "I don't need Jacket Magnetic Mount",
    ):
        result = eng.detect_multi_select_removal(phrase, [attr], filled_multi)
        assert result is not None, f"expected a match for: {phrase!r}"
        assert result[1] == ["Jacket Magnetic Mount"]
