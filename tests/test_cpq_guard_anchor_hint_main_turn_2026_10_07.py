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


def test_the_bounded_post_loop_path_carries_both_the_cache_and_the_wording():
    s = get_settings()
    s.cpq_post_loop_timeout_enabled = True
    s.cpq_post_loop_timeout_s = 5.0
    seen = _run(True)
    assert isinstance(seen["loop"]["_dt_cache"], dict) and seen["loop"]["product_anchor_hint"] == WORDING
    assert seen["fill"]["_dt_cache"] is seen["loop"]["_dt_cache"] and seen["fill"]["product_anchor_hint"] == WORDING


# --- the shared helper, and every session-bearing caller of the loop / auto_fill uses it ---------------------------
import ast
import pathlib
from types import SimpleNamespace

from aryx.cpq.guard_anchor_hint import guard_anchor_hint_kwargs

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src" / "aryx" / "api"
SESSION_CALLERS = [
    *(f"ask_attr_recompute/ask_{n}_recompute.py" for n in (
        "attr_activation", "attr_clear", "bulk_quantity", "cascade_multi", "cascade", "multi_select_removal")),
    "ask_country_change_revalidate.py",
    "ask_turn_steps/ask_step10_recompute_pending.py",
]


@pytest.mark.parametrize("wording,flag,expected", [
    (WORDING, True, {"product_anchor_hint": WORDING}),
    (WORDING, False, {}),
    ("", True, {}),
    (None, True, {}),
])
def test_the_helper_returns_the_wording_only_with_the_flag_on_and_wording_present(wording, flag, expected):
    get_settings().cpq_not_applicable_guard_enabled = flag
    assert guard_anchor_hint_kwargs(SimpleNamespace(product_anchor_question=wording)) == expected


def test_a_session_without_the_attribute_gets_no_kwargs():
    get_settings().cpq_not_applicable_guard_enabled = True
    assert guard_anchor_hint_kwargs(SimpleNamespace()) == {}


@pytest.mark.parametrize("rel", SESSION_CALLERS)
def test_every_loop_and_auto_fill_call_with_a_session_passes_the_wording(rel):
    """Pins the rollout: a future call added here without the helper reintroduces the silent no-op."""
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("evaluate_rules_loop", "auto_fill")
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "_cpq_engine"]
    assert calls, rel

    def passes_wording(call):
        text = ast.dump(call)
        return "guard_anchor_hint_kwargs" in text or any(k.arg == "product_anchor_hint" for k in call.keywords) \
            or "_loop_kwargs" in text

    assert all(passes_wording(c) for c in calls), rel
