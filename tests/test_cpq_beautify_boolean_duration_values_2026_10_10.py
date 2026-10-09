"""Beautify keeps Yes/No and duration values behind cpq_beautify_show_boolean_and_duration_values_enabled.

ws 1267, APX 3000: Data Cable and Data Link Manager CD were filled "NO" from the base model's Defaultinattr row,
but `_is_summary_excluded` drops non-mandatory boolean and "N Years" values, so Beautify never showed them although
the real screen does. With the flag on Beautify keeps them; the chat summary keeps excluding them.
"""
from __future__ import annotations

import pytest

from aryx.config import get_settings
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr


@pytest.fixture
def flag():
    s = get_settings()
    previous = s.cpq_beautify_show_boolean_and_duration_values_enabled
    s.cpq_beautify_show_boolean_and_duration_values_enabled = True
    yield s
    s.cpq_beautify_show_boolean_and_duration_values_enabled = previous


def _attr(eid: int, vn: str, label: str) -> ConfigAttr:
    return ConfigAttr(entity_id=eid, variable_name=vn, display_label=label, required=False, default_value="", options=[])


ATTRS = [
    _attr(1, "cableDataCable_astro", "Data Cable"),
    _attr(2, "serviceDuration_astro", "Service Duration"),
    _attr(3, "beltClipType_astro", "Carry Type"),
]
FILLED = {"cableDataCable_astro": "No", "serviceDuration_astro": "3 Years", "beltClipType_astro": "2.5 Inch"}


def _labels(rows: list[dict[str, str]]) -> set[str]:
    return {r["label"] for r in rows}


def test_flag_off_drops_boolean_and_duration_rows():
    rows = CpqEngine().beautify_rows("APX 3000", FILLED, ATTRS)
    assert "Carry Type" in _labels(rows)
    assert {"Data Cable", "Service Duration"}.isdisjoint(_labels(rows))


def test_flag_on_keeps_boolean_and_duration_rows(flag):
    rows = CpqEngine().beautify_rows("APX 3000", FILLED, ATTRS)
    assert {"label": "Data Cable", "value": "No"} in rows
    assert {"label": "Service Duration", "value": "3 Years"} in rows
    assert {"label": "Carry Type", "value": "2.5 Inch"} in rows


def test_flag_on_leaves_the_summary_unchanged(flag):
    pairs = CpqEngine().filled_summary_pairs(FILLED, ATTRS)
    assert ("Carry Type", "2.5 Inch") in pairs
    assert {"Data Cable", "Service Duration"}.isdisjoint({label for label, _ in pairs})


def test_flag_on_keeps_a_boolean_attribute_only_with_a_yes_no_value(flag):
    raw = ConfigAttr(entity_id=5, variable_name="rawFlag_astro", display_label="Raw Flag", required=False,
                     default_value="", options=[], select_type="boolean")
    worded = ConfigAttr(entity_id=6, variable_name="wordFlag_astro", display_label="Word Flag", required=False,
                        default_value="", options=[], select_type="boolean")
    rows = CpqEngine().beautify_rows("APX 3000", {"rawFlag_astro": "1", "wordFlag_astro": "Yes"}, [raw, worded])
    assert "Raw Flag" not in _labels(rows)
    assert {"label": "Word Flag", "value": "Yes"} in rows


def test_flag_on_still_applies_the_other_exclusions(flag):
    hidden = ConfigAttr(entity_id=4, variable_name="hiddenFlag_astro", display_label="Hidden Flag", required=False,
                        default_value="", options=[], hidden=True)
    rows = CpqEngine().beautify_rows("APX 3000", {"hiddenFlag_astro": "No"}, [hidden])
    assert "Hidden Flag" not in _labels(rows)
