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
from aryx.raven_log import raven_log, submit_ctx, would_log
from aryx.worker.job_partial import note_hidden

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
            if would_log("DEBUG"):
                raven_log("DEBUG", "P4", "ingest.mentions.chunk attempt succeeded",
                          context={"doc_id": chunk.doc_id[:8], "chunk": chunk.chunk_index, "attempt": attempt,
                                   "max_attempts": max_attempts, "result": "ok"})
            return chunk, result, None
        except Exception as exc:  # noqa: BLE001 — any provider/parse failure is retryable
            last_exc = exc
            if attempt < max_attempts:
                logger.warning(
                    "extraction attempt %d/%d failed chunk=%d doc=%s error=%s — retrying",
                    attempt, max_attempts, chunk.chunk_index, chunk.doc_id[:8], exc,
                )
                raven_log("DEBUG", "P4", "ingest.mentions.chunk retry scheduled",
                          context={"doc_id": chunk.doc_id[:8], "chunk": chunk.chunk_index, "attempt": attempt,
                                   "max_attempts": max_attempts, "backoff_ms": int(retry_delay * attempt * 1000),
                                   "triggering_error": type(exc).__name__, "recovery_selected": "retry",
                                   "exit_condition": "attempts_remaining", "result": "retrying"})
                time.sleep(retry_delay * attempt)
            else:
                raven_log("DEBUG", "P4", "ingest.mentions.chunk gave up after last attempt",
                          context={"doc_id": chunk.doc_id[:8], "chunk": chunk.chunk_index, "attempt": attempt,
                                   "max_attempts": max_attempts, "triggering_error": type(exc).__name__,
                                   "recovery_selected": "give_up", "exit_condition": "attempts_exhausted",
                                   "result": "failed"})
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
    t0 = time.monotonic()
    last_error_class = ""
    raven_log("DEBUG", "P4", "ingest.mentions.start extraction settings",
              context={"chunks": total, "workers": workers, "max_attempts": max_attempts,
                       "retry_delay_s": retry_delay, "flush_every": flush_every,
                       "has_progress_callback": on_progress is not None, "has_context": bool(context)})

    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {
            submit_ctx(pool, _extract_chunk_with_retry, chunk, broker, system_prompt,
                       max_attempts, retry_delay): chunk
            for chunk in chunks
        }
        for fut in as_completed(futures):
            chunk, result, last_exc = fut.result()
            completed += 1
            if result is None:
                failed_chunks += 1
                last_error_class = type(last_exc).__name__ if last_exc is not None else ""
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
                if would_log("DEBUG"):
                    raven_log("DEBUG", "P4", "ingest.mentions.chunk mentions gated",
                              context={"doc_id": chunk.doc_id[:8], "chunk": chunk.chunk_index,
                                       "mentions_returned": len(result.get("mentions", [])),
                                       "kept": len(new_records), "rejected_by_span_gate": new_rejected})

            if on_progress and (completed % flush_every == 0 or completed == total):
                if would_log("DEBUG"):
                    raven_log("DEBUG", "P4", "ingest.mentions.flush progress callback",
                              context={"completed": completed, "total": total, "flushed_records": len(pending_flush),
                                       "selected_option": "flush", "reason_code": "FLUSH_EVERY_OR_LAST"})
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
        note_hidden()
        raven_log("ERROR", "P2", "ingest.mentions.all_failed every chunk failed extraction",
                  error_code="ARYX_ING_LLM_EXTRACT_FAILED",
                  context={"dependency_name": "oci_genai", "operation": "extract_mentions",
                           "duration_ms": int((time.monotonic() - t0) * 1000), "result": "error",
                           "error_class": last_error_class, "attempt": max_attempts, "chunks": total,
                           "failed_chunks": failed_chunks, "model": "cheap_tier",
                           "prompt_version": "unversioned"})
    else:
        raven_log("DEBUG", "P4", "ingest.mentions.done extraction finished",
                  context={"chunks": total, "mentions": len(records), "rejected": rejected,
                           "failed_chunks": failed_chunks, "partial": failed_chunks > 0,
                           "duration_ms": int((time.monotonic() - t0) * 1000)})
    return records
