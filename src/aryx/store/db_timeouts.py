"""Shared helpers for bounding DB calls (Postgres statement_timeout / Oracle call_timeout).

Ported from dev-rv-msi #363/#368/#370 and made Oracle-correct: on python-oracledb
the per-call timeout is ``connection.call_timeout`` (ms); cursor-level
``callTimeout`` does not exist and assigning it is a silent no-op.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from aryx.raven_log import raven_log

logger = logging.getLogger(__name__)

_TIMEOUT_MARKERS = ("ora-03156", "dpy-4024", "statement timeout", "querycanceled")


def looks_like_timeout(exc: BaseException) -> bool:
    """True when the exception looks like a DB call/statement timeout."""
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _TIMEOUT_MARKERS)


def log_if_timeout(exc: BaseException, where: str) -> None:
    """Emit a WARNING when a swallowed DB error is a timeout (vs. 'no rows')."""
    if looks_like_timeout(exc):
        logger.warning("db call timed out in %s: %s", where, exc)
        raven_log("WARN", "P2", "db.call.timed_out swallowed DB error was a call timeout, not 'no rows'",
                  error_code="ARYX_DB_CALL_TIMEOUT",
                  context={"dependency_name": "oracle_adb" if "oracle" in where else "postgres",
                           "operation": where, "duration_ms": None, "result": "timeout",
                           "error_class": type(exc).__name__, "attempt": 1})


def _call_timeout_failed(step: str, exc: BaseException) -> None:
    raven_log("WARN", "P3", f"db.call_timeout.{step}_failed oracle call_timeout not applied",
              error_code="ARYX_DB_CALL_TIMEOUT_CONFIG_FAILED",
              context={"triggering_error": type(exc).__name__, "attempt": 1, "max_attempts": 1,
                       "backoff_ms": 0, "recovery_selected": "continue_unbounded" if step != "restore" else
                       "keep_bounded_value", "fallback_target": None, "exit_condition": "degraded",
                       "result": "degraded", "step": step})


@contextmanager
def oracle_call_timeout(conn: Any, timeout_ms: int) -> Iterator[None]:
    """Set ``conn.call_timeout`` for the block and restore the previous value."""
    previous = None
    have_previous = False
    try:
        previous = conn.call_timeout
        have_previous = True
    except Exception as exc:
        logger.warning("oracle call_timeout: could not read previous value", exc_info=True)
        _call_timeout_failed("read", exc)
    try:
        conn.call_timeout = int(timeout_ms)
    except Exception as exc:
        logger.warning("oracle call_timeout: could not set value", exc_info=True)
        _call_timeout_failed("set", exc)
    try:
        yield
    finally:
        if have_previous:
            try:
                conn.call_timeout = previous
            except Exception as exc:
                logger.warning("oracle call_timeout: could not restore previous value", exc_info=True)
                _call_timeout_failed("restore", exc)
