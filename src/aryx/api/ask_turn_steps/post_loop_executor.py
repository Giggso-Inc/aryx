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


def run_post_loop_bounded(fn: Callable[[], Any], timeout_s: float) -> Any:
    """Run `fn()` in the pool under a copied context; raise HTTP 504 after
    `timeout_s`. Exceptions raised by `fn` propagate unchanged."""
    ctx = contextvars.copy_context()
    future = _POST_LOOP_EXECUTOR.submit(ctx.run, fn)
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
