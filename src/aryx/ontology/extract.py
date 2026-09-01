"""Document entity extraction agent + verbatim-span gate (Inc 8).

Runs on cheap tier; verbatim-span gate is a deterministic, free control:
any mention whose name is absent from its cited span is rejected before it
can reach resolution or the graph.

Provider-shape quirks (Gemini's bare-list envelope, field renames like
entity_type / verbatim_span) are absorbed by aryx.llm_normalize at the
complete_json boundary — this module sees the canonical schema shape only.
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
from aryx.models import DocumentChunk, RawRecord, SourceRef

logger = logging.getLogger(__name__)

_SYSTEM_BASE = (
    "You extract entity mentions from document text for a domain-specific "
    "knowledge graph. For each mention return: "
    "(1) `type` — a singular PascalCase noun that names the REAL-WORLD CONCEPT "
    "being referenced. Use domain-specific types when warranted (Goal, Scope, "
    "Aim, Initiative, Capability, ValueProposition, CustomerSegment, "
    "Milestone, Metric, Feature, Risk, Pricing, MarketSegment, Strategy, "
    "Partner, Competitor, Dataset, KPI, RoadmapItem, etc.). Fall back to "
    "generic NER (Organization, Person, Product, Location, Date) ONLY when "
    "no domain-specific type fits. NEVER use generic words (Entity, Item, "
    "Thing, Concept). "
    "(2) `name` — the exact name as it literally appears in the text. "
    "(3) `attributes` — typed attributes (role, founded, value, owner, etc.). "
    "(4) `span` — a short verbatim excerpt from the text that contains the "
    "name word-for-word. "
    "Only emit a mention when the name appears word-for-word inside the span. "
    "Prefer rich domain types over generic NER. Prefer fewer high-confidence "
    "mentions over many uncertain ones."
)


def _system_prompt(context: str) -> str:
    """Prepend the workspace business context so extraction is domain-aware."""
    if not context.strip():
        return _SYSTEM_BASE
    return (
        f"WORKSPACE CONTEXT (what this knowledge graph is about):\n{context.strip()}\n\n"
        + _SYSTEM_BASE
        + "\n\nUse the workspace context above to decide which entity types "
        "matter. Pull domain-specific concepts (Goal, Scope, Aim, "
        "Initiative, Capability, etc.) when relevant — NOT just generic "
        "Organization/Person/Date."
    )

_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "mentions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "name": {"type": "string"},
                    "attributes": {"type": "object", "additionalProperties": True},
                    "span": {"type": "string"},
                },
                "required": ["type", "name", "span"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["mentions"],
    "additionalProperties": False,
}


def _verbatim_ok(name: str, span: str) -> bool:
    return name.lower() in span.lower()


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


def _mentions_to_records(chunk: DocumentChunk, result: dict) -> tuple[list[RawRecord], int]:
    """Apply the verbatim-span gate; returns (accepted_records, rejected_count)."""
    records: list[RawRecord] = []
    rejected = 0
    for i, mention in enumerate(result.get("mentions", [])):
        name = mention.get("name", "")
        span = mention.get("span", "") or name
        if not name or not mention.get("type") or not _verbatim_ok(name, span):
            rejected += 1
            continue
        mention_id = f"{chunk.doc_id}:{chunk.chunk_index}:{i}"
        records.append(RawRecord(
            source=SourceRef(
                system=chunk.source.system,
                dataset=chunk.source.dataset,
                record_id=mention_id,
            ),
            payload={
                "type": mention["type"],
                "name": name,
                "doc_id": chunk.doc_id,
                "chunk_index": chunk.chunk_index,
                "span": span,
                **(mention.get("attributes") or {}),
            },
        ))
    return records, rejected


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
