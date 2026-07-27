"""Chunk embedding via the broker's embed model (Ollama local or OCI GenAI).

Fail-closed: raises RuntimeError if the broker has no embed model configured
or if the returned dimension doesn't match the expected dim. This prevents
mixed-dim vectors from entering the store silently.
"""
from __future__ import annotations

import logging

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.models import ChunkEmbedding, DocumentChunk

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
        return []

    model_id = broker.embed_model_id
    if not model_id:
        raise RuntimeError(
            "no embed model configured — set broker catalog embed.model"
        )

    batch_size = get_settings().embed_batch_size
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), batch_size):
        batch_texts = [c.text for c in chunks[start:start + batch_size]]
        batch_vectors = broker.embed(batch_texts)
        if not batch_vectors:
            raise RuntimeError(
                f"broker.embed() returned no vectors for model={model_id!r} — "
                "is Ollama running and the model pulled?"
            )
        vectors.extend(batch_vectors)

    dim = len(vectors[0])
    if expected_dim is not None and dim != expected_dim:
        raise RuntimeError(
            f"embed dim mismatch: model={model_id!r} produced {dim}, "
            f"expected {expected_dim}. Update config or re-embed."
        )

    logger.info("embedded chunks=%d model=%s dim=%d batch_size=%d",
                len(chunks), model_id, dim, batch_size)
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
