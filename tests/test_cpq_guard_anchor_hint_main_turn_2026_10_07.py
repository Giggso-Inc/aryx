"""ws 1267 (2026-10-07): the rules loop and the post-loop auto_fill of the main /ask turn were never given the customer's
own wording, so the not-applicable guard (which resolves the device from it) never acted. The wording is now passed to
both calls, only while the guard's flag is on."""
from __future__ import annotations

import pytest

from aryx.config import get_settings
from tests.test_cpq_post_loop_timeout_2026_10_02 import _call, _engine, _session

WORDING = "I want a quote for APX N30 for US"


@pytest.fixture(autouse=True)
def _flags():
    s = get_settings()
    prev = (s.cpq_not_applicable_guard_enabled, s.cpq_post_loop_timeout_enabled)
    s.cpq_post_loop_timeout_enabled = False
    yield
    s.cpq_not_applicable_guard_enabled, s.cpq_post_loop_timeout_enabled = prev


def _run(flag: bool, wording: str = WORDING):
    get_settings().cpq_not_applicable_guard_enabled = flag
    seen: dict = {}
    eng = _engine({})
    base_loop, base_fill = eng.evaluate_rules_loop.side_effect, eng.auto_fill.side_effect
    eng.evaluate_rules_loop.side_effect = lambda *a, **kw: (seen.__setitem__("loop", kw), base_loop(*a, **kw))[1]
    eng.auto_fill.side_effect = lambda *a, **kw: (seen.__setitem__("fill", kw), base_fill(*a, **kw))[1]
    session = _session()
    session.product_anchor_question = wording
    from types import SimpleNamespace
    from unittest.mock import patch
    req = SimpleNamespace(workspace_id=1)
    from aryx.api.ask_turn_steps.ask_step10_recompute_pending import _step10_recompute_pending
    with patch("aryx.api.ask_api._cpq_engine", eng), \
            patch("aryx.api.ask_turn_steps.ask_step10_recompute_pending.grid_narrow_kwargs", return_value={}):
        _step10_recompute_pending({}, [], session, [], [], [], None, {}, set(), set(), [], req, "")
    return seen


def test_with_the_guard_flag_on_both_calls_receive_the_wording():
    seen = _run(True)
    assert seen["loop"]["product_anchor_hint"] == WORDING and seen["fill"]["product_anchor_hint"] == WORDING


def test_with_the_guard_flag_off_neither_call_receives_it():
    seen = _run(False)
    assert "product_anchor_hint" not in seen["loop"] and "product_anchor_hint" not in seen["fill"]


def test_with_no_wording_nothing_is_passed_even_with_the_flag_on():
    seen = _run(True, wording="")
    assert "product_anchor_hint" not in seen["loop"] and "product_anchor_hint" not in seen["fill"]
