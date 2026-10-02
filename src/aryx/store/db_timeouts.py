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


@contextmanager
def oracle_call_timeout(conn: Any, timeout_ms: int) -> Iterator[None]:
    """Set ``conn.call_timeout`` for the block and restore the previous value."""
    previous = None
    have_previous = False
    try:
        previous = conn.call_timeout
        have_previous = True
    except Exception:
        logger.warning("oracle call_timeout: could not read previous value", exc_info=True)
    try:
        conn.call_timeout = int(timeout_ms)
    except Exception:
        logger.warning("oracle call_timeout: could not set value", exc_info=True)
    try:
        yield
    finally:
        if have_previous:
            try:
                conn.call_timeout = previous
            except Exception:
                logger.warning("oracle call_timeout: could not restore previous value", exc_info=True)
