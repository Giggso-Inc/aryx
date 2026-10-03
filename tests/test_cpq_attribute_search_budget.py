"""PR #423 review: cold-cache lookups are bounded.

- The whole lookup runs on a background worker with a time budget; past the
  budget the turn falls back to the normal quote path (never a partial
  result), while the worker finishes and warms the cache.
- Families load in parallel, at most 2 at a time (DB pool headroom).
Behaviour tests with events, not timing benchmarks.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from aryx.api.ask_api import AskRequest
from aryx.api.ask_attribute_search import _route_attribute_search
from aryx.cpq.attribute_search import menu_source
from aryx.cpq.attribute_search.budget import BudgetExceeded, run_with_budget
from aryx.cpq.intent_gateway.intent_gateway import AskRouteDecision
from aryx.cpq.state import ConfigAttr, MenuOption

_MARKER = "aryx.cpq.data_table.data_table_cache._current_invalidation_marker"


@pytest.fixture(autouse=True)
def _fresh():
    menu_source.clear_menu_cache()
    with patch(_MARKER, return_value=1.0):
        yield
    menu_source.clear_menu_cache()


def test_result_within_budget_is_returned():
    assert run_with_budget(lambda: 42, budget_s=5) == 42


def test_over_budget_raises_and_the_work_still_finishes():
    release, done = threading.Event(), threading.Event()

    def slow():
        release.wait(5)
        done.set()
        return "warm"

    t0 = time.monotonic()
    with pytest.raises(BudgetExceeded):
        run_with_budget(slow, budget_s=0.05)
    assert time.monotonic() - t0 < 2
    release.set()
    assert done.wait(5)  # the worker kept going and finished


def test_errors_inside_the_budget_are_re_raised():
    def boom():
        raise RuntimeError("db down")
    with pytest.raises(RuntimeError):
        run_with_budget(boom, budget_s=5)


def test_handler_falls_back_to_the_quote_path_when_over_budget():
    release = threading.Event()
    engine = MagicMock()
    engine.detect_product_mention.return_value = ""
    engine.resolve_product_hint.return_value = None
    req = AskRequest(question="a product with ATT as a carrier", workspace_id=1, history=[],
                     session_data={})
    meta = AskRouteDecision(route="attribute_search", confidence="high",
                            clarifying_question=None, rationale="",
                            attribute_label="carrier", attribute_value="ATT")
    with patch("aryx.api.ask_api._cpq_engine", engine), \
         patch("aryx.api.ask_attribute_search.find_products_by_attribute",
               side_effect=lambda *a, **k: release.wait(5)), \
         patch("aryx.api.ask_attribute_search._budget_s", return_value=0.05):
        t0 = time.monotonic()
        assert _route_attribute_search(req, object(), meta) is None
        assert time.monotonic() - t0 < 2
    release.set()


def test_families_load_in_parallel_but_at_most_two_at_a_time():
    lock, state = threading.Lock(), {"now": 0, "peak": 0}

    def load(reader, ws, family):
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
        attr = ConfigAttr(entity_id=1, variable_name=f"c_{family}", display_label="Carrier",
                          required=False, default_value="",
                          options=[MenuOption(item_value="ATT", display_name="ATT")])
        return [attr], family

    eng = MagicMock()
    eng.list_ingested_families.return_value = [f"F{i}" for i in range(6)]
    eng.load_product_config.side_effect = load
    hits, _ = menu_source.search_menu_options("carrier", "ATT", reader=object(), engine=eng,
                                              workspace_id=1)
    assert {h["model"] for h in hits} == {f"F{i}" for i in range(6)}
    assert state["peak"] == 2


def test_lookups_beyond_the_in_flight_cap_are_refused_at_once():
    from aryx.cpq.attribute_search import budget

    release = threading.Event()
    started = []
    for _ in range(budget._MAX_IN_FLIGHT):
        with pytest.raises(BudgetExceeded):
            run_with_budget(lambda: started.append(1) or release.wait(5), budget_s=0.01)
    t0 = time.monotonic()
    with pytest.raises(BudgetExceeded, match="busy"):
        run_with_budget(lambda: "never runs", budget_s=5)
    assert time.monotonic() - t0 < 0.5
    release.set()
    deadline = time.monotonic() + 5
    while budget._in_flight and time.monotonic() < deadline:
        time.sleep(0.01)
    assert budget._in_flight == 0
    assert run_with_budget(lambda: "ok", budget_s=5) == "ok"


def test_worker_sees_the_callers_context():
    import contextvars

    var = contextvars.ContextVar("run_id", default="-")
    var.set("run-123")
    assert run_with_budget(var.get, budget_s=5) == "run-123"
