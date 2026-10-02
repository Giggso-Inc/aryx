"""Bounded executor for the post-loop auto_fill (port of dev-rv-msi #372).

A small module-level pool so a stalled post-loop `auto_fill` cannot hang the
request forever. Work is submitted through `contextvars.copy_context().run`
so the per-turn LLM usage ContextVar (`llm/llm_runtime_state.py`) and the
run_id log tag (`cpq/logging_context.py`) survive the thread hop -- a plain
`submit` would lose both. Python cannot cancel a running thread: on timeout
the orphan keeps running to completion and its result is discarded.
"""
from __future__ import annotations

import contextvars
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Callable

from fastapi import HTTPException

from aryx.cpq.logging_context import install_run_id_logging

logger = logging.getLogger(__name__)
install_run_id_logging(__name__)

_POST_LOOP_MAX_WORKERS = 8
_POST_LOOP_EXECUTOR = ThreadPoolExecutor(
    max_workers=_POST_LOOP_MAX_WORKERS, thread_name_prefix="cpq-post-loop",
)


_inflight_lock = threading.Lock()
_inflight = 0  # submitted and not yet finished, INCLUDING abandoned timed-out workers
_ordering_warned = False


def _on_done(_future: Any) -> None:
    global _inflight
    with _inflight_lock:
        _inflight -= 1


def warn_if_timeouts_inverted(settings: Any) -> None:
    """Log once if the post-loop timeout is not above the RDB call timeout and
    the tables-cache lock timeout (the flags' documented ordering)."""
    global _ordering_warned
    if _ordering_warned:
        return
    post_loop = float(settings.cpq_post_loop_timeout_s)
    rdb = float(settings.cpq_rdb_call_timeout_ms) / 1000.0
    lock = float(settings.cpq_tables_cache_lock_timeout_s)
    if post_loop <= rdb or post_loop <= lock:
        _ordering_warned = True
        logger.warning(
            "cpq: post-loop timeout %.0fs is not above the RDB call timeout %.0fs "
            "and the tables-cache lock timeout %.0fs; requests may 504 while "
            "their DB work or lock waiters are still running", post_loop, rdb, lock,
        )


def run_post_loop_bounded(fn: Callable[[], Any], timeout_s: float) -> Any:
    """Run `fn()` in the pool under a copied context; raise HTTP 504 after
    `timeout_s`. Exceptions raised by `fn` propagate unchanged. When every
    worker is busy (abandoned timed-out ones count) the call is rejected with
    HTTP 503 immediately instead of queueing, so queue wait never silently
    eats the timeout."""
    global _inflight
    with _inflight_lock:
        busy = _inflight >= _POST_LOOP_MAX_WORKERS
        if not busy:
            _inflight += 1
    if busy:
        logger.error(
            "cpq_perf: post_loop pool saturated (%d in flight, incl. abandoned "
            "workers) -- rejecting with 503", _POST_LOOP_MAX_WORKERS,
        )
        raise HTTPException(
            status_code=503,
            detail="The server is busy processing other configurations. Please try again shortly.",
        )
    ctx = contextvars.copy_context()
    try:
        future = _POST_LOOP_EXECUTOR.submit(ctx.run, fn)
    except BaseException:
        with _inflight_lock:
            _inflight -= 1
        raise
    future.add_done_callback(_on_done)
    try:
        return future.result(timeout=timeout_s)
    except FutureTimeoutError:
        if future.done():
            raise  # fn itself raised TimeoutError (alias on py3.11+); not our timeout
        logger.error(
            "cpq_perf: post_loop_auto_fill TIMED OUT after %.1fs -- returning 504 "
            "(the worker thread keeps running; its result is discarded)", timeout_s,
        )
        raise HTTPException(
            status_code=504,
            detail=(
                "The configuration took too long to process. "
                "Please try again in a moment."
            ),
        ) from None
