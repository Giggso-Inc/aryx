"""docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md is unrelated --
this is a separate, general correctness bug found live 2026-08-24 while
investigating the SVX mounting-type flow.

`_label_collision_prompt` (ask_api.py) rendered the raw internal
`variable_name` ("mountType_viSoln") in the disambiguation prompt instead
of a customer-meaningful label, even though every OTHER place in the flow
that names one of a colliding pair (the real question header, cascade-
announcement text) already uses `CpqEngine.disambiguated_label()` for
exactly this reason. Not SVX-specific -- this is a general fix, so the
test fixtures below deliberately use a NON-SVX label pair.
"""
from __future__ import annotations

from aryx.api.ask_label_collision.ask_label_collision_prompt_and_narrow import _label_collision_prompt
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _attr(vn: str, label: str) -> ConfigAttr:
    return ConfigAttr(
        entity_id=hash(vn) % 100000, variable_name=vn, display_label=label,
        required=False, default_value="",
        options=[MenuOption(item_value="v1", display_name="Opt 1", order=1)],
    )


def test_label_collision_prompt_uses_disambiguated_labels_not_raw_variable_names():
    session = CpqSession()
    collision = [
        _attr("serviceType_astro", "Service Type"),
        _attr("serviceTypeRSM_astro", "Service Type"),
        _attr("serviceTypeAdditionalDMSCoverage_astro", "Service Type"),
    ]

    prompt = _label_collision_prompt(collision, session)

    assert "serviceType_astro" not in prompt
    assert "serviceTypeRSM_astro" not in prompt
    assert "serviceTypeAdditionalDMSCoverage_astro" not in prompt
    assert "Service Type (RSM)" in prompt
    assert "Service Type (Additional DMS Coverage)" in prompt


def test_label_collision_prompt_still_names_a_currently_filled_candidate():
    """The "(currently: ...)" hint must still key off the real
    variable_name in session.display_filled even though the visible
    label text changed."""
    session = CpqSession()
    session.display_filled = {"serviceTypeRSM_astro": "Advanced"}
    collision = [
        _attr("serviceType_astro", "Service Type"),
        _attr("serviceTypeRSM_astro", "Service Type"),
    ]

    prompt = _label_collision_prompt(collision, session)

    assert "Service Type (RSM)** (currently: Advanced)" in prompt


def test_label_collision_prompt_svx_mounting_type_case():
    """The exact live scenario this bug was found in."""
    session = CpqSession()
    collision = [
        _attr("mountType_viSoln", "Mounting Type"),
        _attr("mountingTypeArray_viSoln", "Mounting Type"),
    ]

    prompt = _label_collision_prompt(collision, session)

    assert "mountType_viSoln" not in prompt
    assert "mountingTypeArray_viSoln" not in prompt
    assert "Mounting Type (mount)" in prompt
    assert "Mounting Type (Array)" in prompt
