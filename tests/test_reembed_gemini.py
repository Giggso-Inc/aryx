"""Regression tests for the Gemini embedding backfill script."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from scripts import reembed_gemini


def _paged_pool(*pages: list[tuple[int, str]]) -> tuple[MagicMock, MagicMock]:
    """Build a pool whose cursor returns the supplied query pages."""
    pool = MagicMock()
    connection = pool.connection.return_value.__enter__.return_value
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [*pages, []]
    return pool, cursor


def test_fetch_unembedded_chunks_reads_multiple_database_pages() -> None:
    """Batch size limits every database page rather than slicing one fetchall."""
    pool, cursor = _paged_pool([(1, "a"), (2, "b")], [(3, "c")])

    batches = list(reembed_gemini._fetch_unembedded_chunks(pool, "gemini", 2))

    assert batches == [[(1, "a"), (2, "b")], [(3, "c")]]
    assert cursor.execute.call_count == 3
    params = [call.args[1] for call in cursor.execute.call_args_list]
    assert [item["after_id"] for item in params] == [0, 2, 3]
    assert all(item["batch_size"] == 2 for item in params)


def test_fetch_unembedded_chunks_rejects_nonpositive_batch_size() -> None:
    """Invalid batch sizes fail before opening a database connection."""
    pool = MagicMock()

    with pytest.raises(ValueError, match="batch_size"):
        list(reembed_gemini._fetch_unembedded_chunks(pool, "gemini", 0))

    pool.connection.assert_not_called()


def test_fetch_unembedded_chunks_returns_empty_for_no_rows() -> None:
    """An already-complete backfill yields no work."""
    pool, cursor = _paged_pool()

    batches = list(reembed_gemini._fetch_unembedded_chunks(pool, "gemini", 10))

    assert batches == []
    assert cursor.execute.call_count == 1


def test_main_rejects_partial_embedding_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """A partial API response never marks or logs a full batch as persisted."""
    settings = SimpleNamespace(
        effective_embed_backend=lambda: "gemini",
        effective_dsn=lambda: "postgresql://test",
        embed_model_override="",
    )
    broker = MagicMock()
    broker.embed.return_value = [[0.0] * 768]
    store = MagicMock()
    store._pool = MagicMock()
    monkeypatch.setattr("sys.argv", ["reembed_gemini.py"])

    with (
        patch.object(reembed_gemini, "get_settings", return_value=settings),
        patch.object(reembed_gemini, "default_broker", return_value=broker),
        patch.object(reembed_gemini, "ChunkStore", return_value=store),
        patch.object(
            reembed_gemini,
            "_fetch_unembedded_chunks",
            return_value=iter([[(1, "a"), (2, "b")]]),
        ),
    ):
        exit_code = reembed_gemini.main()

    assert exit_code == 1
    store.save_embeddings.assert_not_called()


def test_main_rejects_mixed_embedding_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every vector must match the persisted column width before any write."""
    settings = SimpleNamespace(
        effective_embed_backend=lambda: "gemini",
        effective_dsn=lambda: "postgresql://test",
        embed_model_override="",
    )
    broker = MagicMock()
    broker.embed.return_value = [[0.0] * 768, [0.0] * 767]
    store = MagicMock()
    store._pool = MagicMock()
    monkeypatch.setattr("sys.argv", ["reembed_gemini.py"])

    with (
        patch.object(reembed_gemini, "get_settings", return_value=settings),
        patch.object(reembed_gemini, "default_broker", return_value=broker),
        patch.object(reembed_gemini, "ChunkStore", return_value=store),
        patch.object(
            reembed_gemini,
            "_fetch_unembedded_chunks",
            return_value=iter([[(1, "a"), (2, "b")]]),
        ),
    ):
        exit_code = reembed_gemini.main()

    assert exit_code == 1
    store.save_embeddings.assert_not_called()
