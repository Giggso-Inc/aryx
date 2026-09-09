"""Bounded-wait primitive shared by the relate stages — abandons stuck
futures instead of blocking indefinitely on one stalled LLM call.

Split out of `pipeline/enrich.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

import logging
from concurrent.futures import FIRST_COMPLETED, Future, wait
from typing import Any, Iterator

logger = logging.getLogger(__name__)


def _drain_with_timeout(
    futures: dict[Future, Any], idle_timeout: float, label: str,
) -> Iterator[tuple[Future, Any]]:
    """Yield (future, key) pairs as they complete; abandon the rest if none
    completes within idle_timeout seconds instead of blocking indefinitely.

    Relate is best-effort enrichment — _relate_isolated() (or a later
    ingest run) still connects anything left isolated — so a single stuck
    LLM call must never hang the whole ingest for the full ARYX_LLM_TIMEOUT.
    Abandoned futures keep running in their worker thread in the background;
    their eventual result is simply discarded (caller must NOT use the
    ThreadPoolExecutor as a `with` block, which would block on exit waiting
    for them — shut it down via `pool.shutdown(wait=False, cancel_futures=True)`).
    """
    pending = set(futures)
    while pending:
        done, pending = wait(pending, timeout=idle_timeout, return_when=FIRST_COMPLETED)
        if not done:
            logger.warning(
                "%s: %d pair(s) still running after %.0fs with no completion — "
                "abandoning the rest of this stage (a later safety net can "
                "still connect them)", label, len(pending), idle_timeout,
            )
            return
        for fut in done:
            yield fut, futures[fut]
