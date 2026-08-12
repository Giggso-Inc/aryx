"""Regression coverage: negating an attribute's ONLY real option must
never silently suppress the whole attribute (docs/CPQ_REGEX_VS_LLM_
ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md row 17).

A deterministic sanity check, not an LLM call — negating an attr with 2+
real options ("exclude Carry Solutions" when Belt Clip is also a real
option) is a genuine, honorable exclusion. Negating an attr's only real
option is contradictory (there's nothing left to fall back to), so it
must not be added to negated_vns the same way.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def test_negating_the_only_real_option_does_not_suppress_the_attribute():
    singleton = ConfigAttr(
        entity_id=1, variable_name="soloAccessory_astro", display_label="Solo Accessory",
        required=False, default_value="", select_type="single",
        options=_menu("Carrying Case Premium"),
    )
    eng = CpqEngine()
    _hints, negated_vns = eng.extract_catalog_hints(
        "exclude the carrying case premium", [singleton],
    )
    assert "soloAccessory_astro" not in negated_vns


def test_negating_one_of_several_real_options_still_suppresses_normally():
    """The existing, correct behavior must be unchanged when there IS a
    real alternative to fall back to."""
    multi_option = ConfigAttr(
        entity_id=1, variable_name="accessoriesSolutionSet_astro", display_label="Accessories",
        required=False, default_value="", select_type="single",
        options=_menu("Carry Solutions Premium", "Belt Clip Standard"),
    )
    eng = CpqEngine()
    _hints, negated_vns = eng.extract_catalog_hints(
        "exclude any carry solutions premium", [multi_option],
    )
    assert "accessoriesSolutionSet_astro" in negated_vns
