"""Unit tests for embed_chunks() batching -- verifies chunks are sent to
broker.embed() in batches of ARYX_EMBED_BATCH_SIZE instead of one giant call,
which risked exceeding the OCI GenAI / Cohere Embed per-request input limit
for large documents (see docs/SCALABILITY_BOTTLENECKS.md).
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from aryx.models import DocumentChunk, SourceRef
from aryx.pipeline.embed import embed_chunks


class _FakeBroker:
    """Records each embed() call's batch size; returns one vector per text."""

    def __init__(self, dim: int = 3) -> None:
        self.embed_model_id = "fake-model"
        self.calls: list[int] = []
        self._dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(len(texts))
        return [[0.1] * self._dim for _ in texts]


def _chunks(n: int) -> list[DocumentChunk]:
    source = SourceRef(system="file", dataset="doc.pdf", record_id="hash")
    return [
        DocumentChunk(doc_id="hash", chunk_index=i, text=f"chunk {i}", source=source)
        for i in range(n)
    ]


def _settings_with_batch_size(size: int) -> MagicMock:
    settings = MagicMock()
    settings.embed_batch_size = size
    return settings


class TestEmbedChunksBatching(unittest.TestCase):
    def test_splits_into_multiple_batches_when_over_limit(self) -> None:
        broker = _FakeBroker()
        with patch("aryx.pipeline.embed.get_settings",
                   return_value=_settings_with_batch_size(50)):
            embed_chunks(_chunks(120), broker)
        # 120 chunks / 50 per batch -> 3 calls: 50, 50, 20
        self.assertEqual(broker.calls, [50, 50, 20])

    def test_single_batch_when_under_limit(self) -> None:
        broker = _FakeBroker()
        with patch("aryx.pipeline.embed.get_settings",
                   return_value=_settings_with_batch_size(50)):
            embed_chunks(_chunks(10), broker)
        self.assertEqual(broker.calls, [10])

    def test_vectors_returned_in_original_chunk_order(self) -> None:
        broker = _FakeBroker()
        with patch("aryx.pipeline.embed.get_settings",
                   return_value=_settings_with_batch_size(2)):
            result = embed_chunks(_chunks(5), broker)
        self.assertEqual([r.chunk_index for r in result], [0, 1, 2, 3, 4])
        self.assertEqual(broker.calls, [2, 2, 1])

    def test_empty_chunks_no_embed_call(self) -> None:
        broker = _FakeBroker()
        with patch("aryx.pipeline.embed.get_settings",
                   return_value=_settings_with_batch_size(50)):
            result = embed_chunks([], broker)
        self.assertEqual(result, [])
        self.assertEqual(broker.calls, [])

    def test_no_model_configured_raises(self) -> None:
        broker = _FakeBroker()
        broker.embed_model_id = None
        with self.assertRaises(RuntimeError):
            embed_chunks(_chunks(3), broker)


if __name__ == "__main__":
    unittest.main()
