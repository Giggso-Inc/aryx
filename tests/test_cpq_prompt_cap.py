"""next_question_prompt: oversized option lists ask for the exact name.

Live finding (workspace 14): the product selector carries the full ~325-model
portfolio in EVERY catalog (its only narrowing rule keys on contract/package
data that is never present in the ingested XML — see
docs/CPQ_PRODUCT_SWITCH_ISSUE.md Issue 1), and the country attr carries ~250
entries. Dumping those as a numbered menu is unusable. Above
_MAX_ENUMERATED_OPTIONS the prompt asks the client to type the exact name
instead — threshold-based and attr-agnostic, no attribute names hardcoded.
"""
from __future__ import annotations

from aryx.cpq.engine import _MAX_ENUMERATED_OPTIONS, CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _attr_with_options(n: int) -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="someBigSelector", display_label="Product",
        required=False, default_value="",
        options=[
            MenuOption(item_value=f"MODEL-{i}", display_name=f"Model {i}", order=i)
            for i in range(1, n + 1)
        ],
    )


def test_oversized_list_asks_for_exact_name_instead_of_enumerating():
    attr = _attr_with_options(_MAX_ENUMERATED_OPTIONS + 100)
    prompt = CpqEngine().next_question_prompt(attr)

    assert "choose one" not in prompt
    assert "1." not in prompt, "must not fall back to a numbered dump"
    assert str(_MAX_ENUMERATED_OPTIONS + 100) in prompt, "must state how many options exist"
    assert "exact name" in prompt
    # First few options surface as examples so the client has a pattern to follow.
    assert "Model 1" in prompt and "Model 2" in prompt and "Model 3" in prompt
    # And a pointer to the full list stays available via the options-query path.
    assert "what are the options" in prompt


def test_small_list_still_enumerates_unchanged():
    attr = _attr_with_options(5)
    prompt = CpqEngine().next_question_prompt(attr)

    assert "**Product** — choose one:" in prompt
    for i in range(1, 6):
        assert f"{i}. Model {i}" in prompt


def test_threshold_boundary_still_enumerates():
    attr = _attr_with_options(_MAX_ENUMERATED_OPTIONS)
    prompt = CpqEngine().next_question_prompt(attr)

    assert "choose one" in prompt, "exactly the threshold must still enumerate"


def test_constraint_narrowing_below_threshold_restores_the_menu():
    """A big master list narrowed by an active constraint to a handful of
    values must present the narrowed menu — the cap keys off the EFFECTIVE
    list, not the raw option count."""
    attr = _attr_with_options(_MAX_ENUMERATED_OPTIONS + 100)
    allowed = [f"MODEL-{i}" for i in range(1, 4)]
    prompt = CpqEngine().next_question_prompt(attr, constrained_item_values=allowed)

    assert "choose one" in prompt
    assert "1. Model 1" in prompt and "3. Model 3" in prompt
    assert "Model 4" not in prompt


def test_typed_exact_name_still_matches_on_an_oversized_list():
    """The reply path the new prompt relies on: apply_answer resolves a
    typed display name against the full option list unchanged."""
    attr = _attr_with_options(_MAX_ENUMERATED_OPTIONS + 100)
    result = CpqEngine().apply_answer(attr, "Model 42")

    assert result is not None
    item_value, display = result
    assert item_value == "MODEL-42"
    assert display == "Model 42"
