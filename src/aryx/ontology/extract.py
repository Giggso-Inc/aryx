"""Document entity extraction agent + verbatim-span gate (Inc 8).

Runs on cheap tier; verbatim-span gate is a deterministic, free control:
any mention whose name is absent from its cited span is rejected before it
can reach resolution or the graph.

Provider-shape quirks (Gemini's bare-list envelope, field renames like
entity_type / verbatim_span) are absorbed by aryx.llm.llm_normalize at the
complete_json boundary — this module sees the canonical schema shape only.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`extract_prompt.py` (system prompt + JSON schema) and
`extract_records.py` (verbatim-span gate + mention-to-RawRecord mapping),
both re-imported here. `_extract_chunk_with_retry`/`extract_mentions`
stay here as a deliberate exception: `complete_json` is directly
whitebox-patched (`aryx.ontology.extract.complete_json`) by
`test_extract_mentions_retry.py`/`test_extract_mentions_concurrency.py`
and called only from `_extract_chunk_with_retry`.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.llm import complete_json
from aryx.models import DocumentChunk, RawRecord
from aryx.ontology.extract_prompt import _SCHEMA, _system_prompt
from aryx.ontology.extract_records import _mentions_to_records, _verbatim_ok

__all__ = ["extract_mentions"]

logger = logging.getLogger(__name__)


def _extract_chunk_with_retry(
    chunk: DocumentChunk, broker: Broker, system_prompt: str,
    max_attempts: int, retry_delay: float,
) -> tuple[DocumentChunk, dict | None, Exception | None]:
    """Run one chunk's LLM call with retry; returns (chunk, result_or_None, last_error)."""
    user = json.dumps({"chunk_index": chunk.chunk_index, "text": chunk.text})
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = complete_json(broker, "cheap", system_prompt, user, _SCHEMA)
            return chunk, result, None
        except Exception as exc:  # noqa: BLE001 — any provider/parse failure is retryable
            last_exc = exc
            if attempt < max_attempts:
                logger.warning(
                    "extraction attempt %d/%d failed chunk=%d doc=%s error=%s — retrying",
                    attempt, max_attempts, chunk.chunk_index, chunk.doc_id[:8], exc,
                )
                time.sleep(retry_delay * attempt)
    return chunk, None, last_exc


def extract_mentions(
    chunks: list[DocumentChunk], broker: Broker, context: str = "",
    on_progress: Callable[[int, int, list[RawRecord]], None] | None = None,
) -> list[RawRecord]:
    """Extract entity mentions from document chunks via the cheap LLM tier.

    Args:
        chunks: PII-screened chunks from clean_text.chunk_pages().
        broker: Model broker; extraction runs on the cheap tier.
        context: Workspace business context — folded into the system prompt
            so the LLM extracts domain-specific entity types instead of
            generic NER categories.
        on_progress: Optional callback invoked every
            ARYX_EXTRACT_MENTION_PROGRESS_FLUSH_CHUNKS completed chunks (and
            once more at the end), as (completed, total, new_records_since_last_call).
            Lets callers persist partial progress for very large documents —
            see the durability note below.

    Returns:
        RawRecord list where each record is one entity mention that passed the
        verbatim-span gate. Mentions whose name is absent from their cited span
        are silently dropped (logged at DEBUG).

    Reliability: a single malformed/unparseable JSON response from the LLM
    (observed with local models under load — occasional truncated or
    non-conforming generations) used to drop that chunk permanently with no
    retry. If that hit every chunk of a document in one run, the whole
    document silently produced zero discovered types — indistinguishable
    from "this document has no entities." Each chunk's call is now retried
    (ARYX_EXTRACT_MENTION_RETRIES attempts, linear backoff) before being
    counted as a real failure; failed_chunks in the log line tells you when
    that safety net actually fired.

    Throughput: chunks used to be processed strictly one at a time — a
    50-page PDF (~330 chunks) measured at 36 minutes wall-clock, so a
    1000+ page document would take many hours serially, and could exceed
    per_doc_timeout before finishing. Chunks are now processed concurrently
    (ARYX_EXTRACT_MENTION_WORKERS, default 4) via a bounded thread pool —
    each chunk's own retry loop still runs independently, so one chunk
    erroring never blocks the others.

    Durability: `on_progress` lets the caller flush partial results as they
    land, instead of only receiving the full record list at the very end —
    if per_doc_timeout expires (or the process crashes) partway through a
    long document, whatever was flushed survives instead of the whole
    document's extraction work being silently discarded.
    """
    settings = get_settings()
    max_attempts = max(1, settings.extract_mention_retries)
    retry_delay = settings.extract_mention_retry_delay
    workers = max(1, settings.extract_mention_workers)
    flush_every = max(1, settings.extract_mention_progress_flush_chunks)
    total = len(chunks)

    records: list[RawRecord] = []
    rejected = 0
    failed_chunks = 0
    completed = 0
    pending_flush: list[RawRecord] = []
    system_prompt = _system_prompt(context)

    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {
            pool.submit(_extract_chunk_with_retry, chunk, broker, system_prompt,
                       max_attempts, retry_delay): chunk
            for chunk in chunks
        }
        for fut in as_completed(futures):
            chunk, result, last_exc = fut.result()
            completed += 1
            if result is None:
                failed_chunks += 1
                logger.warning(
                    "extraction failed chunk=%d doc=%s after %d attempt(s), giving up: %s",
                    chunk.chunk_index, chunk.doc_id[:8], max_attempts, last_exc,
                )
            else:
                logger.info("[step 8/8] extract  chunk=%d mentions=%d  doc=%s",
                            chunk.chunk_index, len(result.get("mentions", [])), chunk.doc_id[:8])
                new_records, new_rejected = _mentions_to_records(chunk, result)
                records.extend(new_records)
                pending_flush.extend(new_records)
                rejected += new_rejected

            if on_progress and (completed % flush_every == 0 or completed == total):
                on_progress(completed, total, pending_flush)
                pending_flush = []
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    logger.info("extract_mentions chunks=%d mentions=%d rejected=%d failed_chunks=%d",
                len(chunks), len(records), rejected, failed_chunks)
    if failed_chunks and not records:
        logger.warning(
            "extract_mentions: ALL %d chunk(s) failed extraction after retries — "
            "0 discovered types is due to LLM extraction failure, not an empty document",
            failed_chunks,
        )
    return records
