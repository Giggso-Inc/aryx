"""Tests for CpqEngine.apply_answer's free-text fallback accepting a real
catalog code that collides with the "no selection" sentinel list —
live incident 2026-09-25 (Region loop, workspace 93/110).

Root cause: an optionless attr (e.g. modelSelectionRegion_astro, whose
only legal value is the literal catalog code "NA" = North America) can
only ever be answered through apply_answer's free-text fallback -- every
other tier requires attr.options, which this attr has none of. That
fallback gated acceptance on _valid(), the same guard auto_fill uses to
avoid ever BLINDLY GUESSING a placeholder-looking value ("na", "none",
"0", "any", ... — see _NONE_VALUES). Reusing it for a customer's own
DELIBERATE typed answer was wrong: "NA" is a real, correct reply here,
not the engine guessing — live-confirmed to reject it every time with no
options to fall back to, producing an unrecoverable infinite re-ask loop.

Fixed by switching that one branch to _presentable()/_DISPLAY_EMPTY —
already the narrower, "genuinely empty/placeholder" set (deliberately
excludes "na", "0", etc. per its own docstring) that this exact
distinction was designed for, just never wired to apply_answer's
free-text path before.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr


@pytest.fixture(autouse=True)
def _flag_on(request):
    """cpq_free_text_presentable_enabled on, except for the flag-off test."""
    on = "flag_off" not in request.node.name
    cfg = SimpleNamespace(cpq_free_text_presentable_enabled=on)
    with patch("aryx.cpq.turn_intent.apply.get_settings", lambda: cfg):
        yield


def _optionless_attr(vn: str = "modelSelectionRegion_astro") -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name=vn, display_label="Region",
        required=True, default_value="", options=[],
    )


def test_real_catalog_code_colliding_with_none_values_is_accepted():
    engine = CpqEngine()
    result = engine.apply_answer(_optionless_attr(), "NA")
    assert result == ("NA", "NA")


def test_lowercase_reply_still_accepted():
    engine = CpqEngine()
    result = engine.apply_answer(_optionless_attr(), "na")
    assert result == ("na", "na")


def test_ordinary_free_text_still_accepted_unchanged():
    """Confirms the fix is additive -- a normal free-text reply for an
    optionless attr still works exactly as before."""
    engine = CpqEngine()
    result = engine.apply_answer(_optionless_attr("someFreeTextField_astro"), "United States")
    assert result == ("United States", "United States")


def test_genuinely_empty_placeholder_replies_still_rejected():
    """_DISPLAY_EMPTY is narrower than _NONE_VALUES but not empty -- a
    truly content-free reply must still be rejected, not accepted as if
    it were real data."""
    engine = CpqEngine()
    for placeholder in ("", "--", "select...", "choose", "none", "null", "undefined"):
        assert engine.apply_answer(_optionless_attr(), placeholder) is None, placeholder


def test_constrained_allowed_set_still_blocks_the_free_text_tier():
    """The free-text fallback only applies when allowed is None (no active
    constraint narrowing) -- an optionless attr under an active
    constraint must still fall through to a hard miss, unchanged."""
    engine = CpqEngine()
    result = engine.apply_answer(_optionless_attr(), "NA", constrained_item_values=["US"])
    assert result is None


def test_attr_with_real_options_never_reaches_the_free_text_tier():
    """Regression guard: an attr that DOES have options must never accept
    "NA" as free text just because none of the option-matching tiers
    happened to match -- the free-text tier is gated on `not attr.options`
    and must stay that way."""
    from aryx.cpq.state import MenuOption

    attr = ConfigAttr(
        entity_id=2, variable_name="hasOptionsAttr_astro", display_label="Has Options",
        required=False, default_value="",
        options=[MenuOption(item_value="US", display_name="United States", order=0)],
    )
    engine = CpqEngine()
    assert engine.apply_answer(attr, "NA") is None


def test_flag_off_keeps_valid_gate_and_rejects_na():
    """Flag off is byte-identical to the old behaviour: _valid() rejects NA."""
    engine = CpqEngine()
    assert engine.apply_answer(_optionless_attr(), "NA") is None
    assert engine.apply_answer(_optionless_attr("x_astro"), "United States") == (
        "United States", "United States")


def test_flag_defaults_off():
    from aryx.config.config_cpq_intent import CpqIntentSettingsMixin

    field = CpqIntentSettingsMixin.model_fields["cpq_free_text_presentable_enabled"]
    assert field.default is False
