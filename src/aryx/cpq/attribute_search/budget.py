"""Run an attribute-search lookup with a time budget (PR #423 review).

A cold catalog cache can take tens of seconds to load (~10-17 s per
family on workspace 704). Past the budget the caller falls back to the
normal quote path -- never a partial result, which could auto-start a
quote for the wrong family -- while the worker keeps running and warms
the caches, so the next question is fast. Same pattern as
classify_intent's timeout (the future is abandoned, not cancelled).

At most 2 lookups run at once, so with menu_source's 2 parallel family
loads the feature holds at most 4 database connections. At most 4 may be
in flight (running or queued): beyond that a lookup is refused at once,
so a database outage can't pile up a backlog of long scans that all hit
the database the moment it recovers. Workers run in a copy of the
caller's context, so request-scoped log fields (run_id) carry over.
"""
from __future__ import annotations

import concurrent.futures
import contextvars
import threading
from typing import Callable, TypeVar

T = TypeVar("T")

_MAX_IN_FLIGHT = 4
_LOOKUP_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="attr-search-lookup",
)
_in_flight = 0
_in_flight_lock = threading.Lock()


class BudgetExceeded(Exception):
    """The lookup didn't finish within its budget, or too many are already in flight."""


def _finished(_future: concurrent.futures.Future) -> None:
    """Done-callback: one fewer lookup in flight."""
    global _in_flight
    with _in_flight_lock:
        _in_flight -= 1


def run_with_budget(fn: Callable[[], T], *, budget_s: float) -> T:
    """Return fn()'s result, or raise BudgetExceeded after `budget_s` seconds.

    Raises BudgetExceeded at once when 4 lookups are already in flight.
    Exceptions raised by fn() are re-raised unchanged.
    """
    global _in_flight
    with _in_flight_lock:
        if _in_flight >= _MAX_IN_FLIGHT:
            raise BudgetExceeded("attribute search busy: lookups already in flight")
        _in_flight += 1
    future = _LOOKUP_POOL.submit(contextvars.copy_context().run, fn)
    future.add_done_callback(_finished)
    try:
        return future.result(timeout=budget_s)
    except concurrent.futures.TimeoutError as exc:
        raise BudgetExceeded(f"attribute search exceeded {budget_s:.0f}s") from exc
