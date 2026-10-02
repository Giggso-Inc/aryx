"""Single-document ingest pipeline + hard wall-clock timeout wrapper.

Split out of `connectors/doc_router.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.connectors.doc_router_select import _connector_for, _content_hash
from aryx.models import RawRecord, SourceRef
from aryx.ontology.extract import extract_mentions
from aryx.pipeline.clean_text import chunk_pages
from aryx.pipeline.embed import embed_chunks
from aryx.pipeline.pii import screen_chunks
from aryx.raven_log import raven_log, submit_ctx
from aryx.store.chunk_store import ChunkStore

logger = logging.getLogger(__name__)

# Hard wall-clock budget per document — a hang in parse / OCR / embed /
# extract is abandoned so the batch finishes. Override with ARYX_PER_DOC_TIMEOUT.
_PER_DOC_TIMEOUT = get_settings().per_doc_timeout

# Max documents processed concurrently. Default 1 (sequential) for CPU Ollama
# where parallelism adds queue overhead without throughput gain. Set to 3-5
# when using a cloud LLM (Anthropic/OpenAI) that handles concurrent requests.
_DOC_WORKERS = get_settings().doc_workers


def _log_timed_out(path: Path, elapsed: float) -> None:
    """Log a FuturesTimeout with the real elapsed time, not the configured budget.

    future.result(timeout=_PER_DOC_TIMEOUT) raises the same TimeoutError whether
    the outer per-document budget genuinely expired, or an inner call (e.g. the
    embedding HTTP request) already failed with its own, shorter timeout — since
    Python unifies socket.timeout/TimeoutError/concurrent.futures.TimeoutError
    into one class. Elapsed time distinguishes the two: it will sit near
    _PER_DOC_TIMEOUT for a genuine outer expiry, and well under it when an inner
    call is what actually failed.
    """
    raven_log("DEBUG", "P4", "ingest.doc.timeout decision outer budget or inner call",
              context={"filename": path.name, "elapsed_s": round(elapsed, 1), "budget_s": _PER_DOC_TIMEOUT,
                       "selected_option": "outer_budget" if elapsed >= _PER_DOC_TIMEOUT * 0.95 else "inner_call",
                       "available_options": ["outer_budget", "inner_call"], "reason_code": "ELAPSED_VS_BUDGET"})
    if elapsed >= _PER_DOC_TIMEOUT * 0.95:
        logger.error(
            "ingest TIMED OUT path=%s after %.1fs — exceeded the per-document "
            "budget (ARYX_PER_DOC_TIMEOUT=%ss); skipping; batch continues",
            path.name, elapsed, _PER_DOC_TIMEOUT,
        )
    else:
        logger.error(
            "ingest TIMED OUT path=%s after %.1fs — an inner call timed out well "
            "before the %ss per-document budget (ARYX_PER_DOC_TIMEOUT); "
            "skipping; batch continues",
            path.name, elapsed, _PER_DOC_TIMEOUT,
        )


def ingest_document(
    path: Path, system: str, broker: Broker, chunk_store: ChunkStore,
    chunk_size: int, chunk_overlap: int, expected_embed_dim: int,
    run_pii: bool = True, context: str = "",
    on_progress: Callable[[int, int, list[RawRecord]], None] | None = None,
) -> list[RawRecord]:
    t0 = time.monotonic()
    doc_id = _content_hash(path)
    source = SourceRef(system=system, dataset=path.stem, record_id=doc_id)
    pages = list(_connector_for(path).extract_pages())
    logger.info("[step 1/8] pages=%d  path=%s", len(pages), path.name)
    raven_log("DEBUG", "P4", "ingest.doc.step 1/8 pages read",
              context={"step": "1/8", "filename": path.name, "doc_id": doc_id[:8], "pages": len(pages),
                       "zero_pages": len(pages) == 0, "duration_ms": int((time.monotonic() - t0) * 1000)})
    chunks = chunk_pages(pages, source=source, doc_id=doc_id,
                         chunk_size=chunk_size, overlap=chunk_overlap)
    logger.info("[step 2/8] chunks=%d  doc_id=%s", len(chunks), doc_id[:8])
    raven_log("DEBUG", "P4", "ingest.doc.step 2/8 chunked",
              context={"step": "2/8", "doc_id": doc_id[:8], "chunks": len(chunks), "chunk_size": chunk_size,
                       "chunk_overlap": chunk_overlap, "duration_ms": int((time.monotonic() - t0) * 1000)})
    if run_pii:
        logger.info("[step 3/8] pii screening  chunks=%d", len(chunks))
        chunks = screen_chunks(chunks)
        raven_log("DEBUG", "P4", "ingest.doc.step 3/8 pii screened",
                  context={"step": "3/8", "doc_id": doc_id[:8], "chunks": len(chunks), "run_pii": True,
                           "duration_ms": int((time.monotonic() - t0) * 1000)})
    else:
        raven_log("DEBUG", "P4", "ingest.doc.step 3/8 pii skipped",
                  context={"step": "3/8", "doc_id": doc_id[:8], "run_pii": False, "reason_code": "RUN_PII_FALSE"})
    doc_db_id = chunk_store.upsert_document(
        content_hash=doc_id, file_name=path.name,
        source_type=path.suffix.lstrip(".").lower(),
        byte_count=path.stat().st_size,
    )
    logger.info("[step 4/8] doc saved  doc_db_id=%d", doc_db_id)
    raven_log("DEBUG", "P4", "ingest.doc.step 4/8 document row saved",
              context={"step": "4/8", "doc_id": doc_id[:8], "doc_db_id": doc_db_id,
                       "bytes": path.stat().st_size, "duration_ms": int((time.monotonic() - t0) * 1000)})
    chunk_db_ids = chunk_store.save_chunks(doc_db_id, chunks)
    logger.info("[step 5/8] chunks saved  ids=%d", len(chunk_db_ids))
    raven_log("DEBUG", "P4", "ingest.doc.step 5/8 chunks saved",
              context={"step": "5/8", "doc_id": doc_id[:8], "chunk_ids": len(chunk_db_ids),
                       "duration_ms": int((time.monotonic() - t0) * 1000)})
    logger.info("[step 6/8] embedding  chunks=%d", len(chunks))
    embeddings = embed_chunks(chunks, broker, expected_dim=expected_embed_dim)
    logger.info("[step 7/8] embeddings=%d  saving to db", len(embeddings))
    raven_log("DEBUG", "P4", "ingest.doc.step 7/8 embeddings computed",
              context={"step": "7/8", "doc_id": doc_id[:8], "embeddings": len(embeddings), "chunks": len(chunks),
                       "expected_dim": expected_embed_dim, "duration_ms": int((time.monotonic() - t0) * 1000)})
    chunk_store.save_embeddings(chunk_db_ids, embeddings)
    logger.info("[step 8/8] extracting mentions  chunks=%d", len(chunks))
    records = extract_mentions(chunks, broker, context=context, on_progress=on_progress)
    logger.info("[ingest done] path=%s  chunks=%d  mentions=%d  doc_id=%s",
                path.name, len(chunks), len(records), doc_id[:8])
    raven_log("DEBUG", "P4", "ingest.doc.step 8/8 mentions extracted",
              context={"step": "8/8", "filename": path.name, "doc_id": doc_id[:8], "chunks": len(chunks),
                       "mentions": len(records), "zero_mentions": len(records) == 0,
                       "duration_ms": int((time.monotonic() - t0) * 1000)})
    return records


def _ingest_with_timeout(
    path: Path, system: str, broker: Broker, chunk_store: ChunkStore,
    chunk_size: int, chunk_overlap: int, expected_embed_dim: int,
    run_pii: bool, context: str,
    on_progress: Callable[[int, int, list[RawRecord]], None] | None = None,
) -> list[RawRecord]:
    """ingest_document under a hard timeout; raises FuturesTimeout on hang."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = submit_ctx(
            pool, ingest_document, path, system, broker, chunk_store,
            chunk_size, chunk_overlap, expected_embed_dim, run_pii, context,
            on_progress,
        )
        return future.result(timeout=_PER_DOC_TIMEOUT)
