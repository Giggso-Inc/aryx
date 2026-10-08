"""Regression test for the `count_turn_intents` arg-shift bug: it used to
call `detect_change_request`/`detect_change_requests_multi` without the
required leading `engine` argument, silently shifting every other argument
one slot. Caught by a blanket `except Exception: logger.debug(...)` in this
diagnostic-only path, so the bug never raised anywhere visible -- it just
quietly dropped the "change:" hit for every message, discovered live via
DEBUG logging on workspace 1267/Astro25Configdata (2026-10-08).
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption
from aryx.cpq.turn_intent import count_turn_intents
from aryx.cpq.turn_intent.change_request import (
    detect_change_request,
    detect_change_requests_multi,
)


def _color_attr() -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="colorAttr", display_label="Color",
        required=True, default_value="Red",
        options=[MenuOption(item_value="Red", display_name="Red"),
                 MenuOption(item_value="Blue", display_name="Blue")],
    )


def test_count_turn_intents_detects_change_request_via_engine() -> None:
    engine = CpqEngine()
    attr = _color_attr()
    filled = {"colorAttr": "Red"}

    hits = count_turn_intents(engine, "change the color to Blue", [attr], filled, None)

    assert any(h.startswith("change") for h in hits), hits


def test_count_turn_intents_is_a_bound_engine_method() -> None:
    # Was previously a @staticmethod, which is why the engine instance
    # could never reach detect_change_request/detect_change_requests_multi.
    engine = CpqEngine()
    attr = _color_attr()
    filled = {"colorAttr": "Red"}

    hits = engine.count_turn_intents("change the color to Blue", [attr], filled, None)

    assert any(h.startswith("change") for h in hits), hits


def test_detect_change_request_requires_leading_engine_arg() -> None:
    # Direct sanity check on the detector signature count_turn_intents
    # must forward `engine` to -- guards against a future regression
    # re-dropping the argument.
    engine = CpqEngine()
    attr = _color_attr()
    filled = {"colorAttr": "Red"}

    result = detect_change_request(engine, "change the color to Blue", [attr], filled, None)
    assert result is not None
    assert result[0].variable_name == "colorAttr"

    multi = detect_change_requests_multi(engine, "change the color to Blue", [attr], filled, None)
    assert multi and multi[0][0].variable_name == "colorAttr"
