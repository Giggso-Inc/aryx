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
