"""Chunk embedding via the broker's embed model (Ollama local or OCI GenAI).

Fail-closed: raises RuntimeError if the broker has no embed model configured
or if the returned dimension doesn't match the expected dim. This prevents
mixed-dim vectors from entering the store silently.
"""
from __future__ import annotations

import logging
import time

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.models import ChunkEmbedding, DocumentChunk
from aryx.raven_log import current_run_id, raven_log, would_log

logger = logging.getLogger(__name__)


def embed_chunks(
    chunks: list[DocumentChunk],
    broker: Broker,
    expected_dim: int | None = None,
) -> list[ChunkEmbedding]:
    """Embed chunks via broker.embed(), in batches (local Ollama or OCI GenAI).

    Sends at most ARYX_EMBED_BATCH_SIZE texts per broker.embed() call --
    a large document's full chunk list used to go in one request, which risks
    exceeding the OCI GenAI / Cohere Embed per-call input limit for anything
    beyond a small document (see docs/SCALABILITY_BOTTLENECKS.md). Mirrors the
    same batching the resolution path already does in resolution/run.py.

    Args:
        chunks: DocumentChunk list to embed.
        broker: Model broker; embed() dispatches to Ollama (local) or OCI GenAI.
        expected_dim: When set, raises RuntimeError on dim mismatch (startup guard).

    Returns:
        One ChunkEmbedding per input chunk, in the same order.
    """
    if not chunks:
        raven_log("DEBUG", "P4", "ingest.embed.skipped no chunks to embed",
                  context={"selected_option": "skip", "available_options": ["skip", "embed"],
                           "reason_code": "NO_CHUNKS", "policy_version": "embed_chunks_v1"})
        return []

    started = time.monotonic()
    model_id = broker.embed_model_id
    if not model_id:
        raven_log("ERROR", "P2", "ingest.embed.no_model no embed model is configured",
                  error_code="ARYX_ING_EMBED_NO_MODEL",
                  context={"dependency_name": "embed_model", "operation": "embed_chunks",
                           "duration_ms": 0, "result": "error", "error_class": "RuntimeError",
                           "attempt": 1, "trace_id": current_run_id(), "chunks": len(chunks)})
        raise RuntimeError(
            "no embed model configured — set broker catalog embed.model"
        )

    batch_size = get_settings().embed_batch_size
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), batch_size):
        batch_texts = [c.text for c in chunks[start:start + batch_size]]
        batch_started = time.monotonic()
        batch_vectors = broker.embed(batch_texts)
        if would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ingest.embed.batch embedded one batch",
                      context={"dependency_name": "embed_model", "operation": "embed_batch",
                               "duration_ms": int((time.monotonic() - batch_started) * 1000),
                               "result": "ok" if batch_vectors else "empty", "error_class": None,
                               "attempt": 1, "trace_id": current_run_id(), "model": model_id,
                               "batch_start": start, "batch_size": len(batch_texts),
                               "vectors_returned": len(batch_vectors or [])})
        if not batch_vectors:
            raven_log("ERROR", "P2", "ingest.embed.empty broker returned no vectors",
                      error_code="ARYX_ING_EMBED_EMPTY",
                      context={"dependency_name": "embed_model", "operation": "embed_batch",
                               "duration_ms": int((time.monotonic() - batch_started) * 1000),
                               "result": "error", "error_class": "RuntimeError", "attempt": 1,
                               "trace_id": current_run_id(), "model": model_id,
                               "batch_start": start, "batch_size": len(batch_texts)})
            raise RuntimeError(
                f"broker.embed() returned no vectors for model={model_id!r} — "
                "is Ollama running and the model pulled?"
            )
        vectors.extend(batch_vectors)

    dim = len(vectors[0])
    if expected_dim is not None and dim != expected_dim:
        raven_log("ERROR", "P2", "ingest.embed.dim_mismatch embedding dimension is not the expected one",
                  error_code="ARYX_ING_EMBED_DIM_MISMATCH",
                  context={"actor": "embed_chunks", "requested_action": "store_vectors",
                           "resource": model_id, "required_permission": "expected_dim",
                           "decision": "deny", "reason_code": "DIM_MISMATCH",
                           "policy_version": "embed_expected_dim", "dim": dim,
                           "expected_dim": expected_dim})
        raise RuntimeError(
            f"embed dim mismatch: model={model_id!r} produced {dim}, "
            f"expected {expected_dim}. Update config or re-embed."
        )

    logger.info("embedded chunks=%d model=%s dim=%d batch_size=%d",
                len(chunks), model_id, dim, batch_size)
    raven_log("INFO", "P4", "ingest.embed.completed chunks embedded",
              context={"task_id": current_run_id(), "final_status": "complete",
                       "duration_ms": int((time.monotonic() - started) * 1000),
                       "stage": "embed", "result": "ok", "reason_code": "EMBEDDED",
                       "impact_scope": "document_chunks", "chunks": len(chunks), "model": model_id,
                       "dim": dim, "batch_size": batch_size,
                       "batches": (len(chunks) + batch_size - 1) // batch_size})
    return [
        ChunkEmbedding(
            chunk_index=chunk.chunk_index,
            doc_id=chunk.doc_id,
            model_id=model_id,
            dim=dim,
            vector=vec,
        )
        for chunk, vec in zip(chunks, vectors)
    ]
