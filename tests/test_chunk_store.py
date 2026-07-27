"""Unit tests for ChunkStore.save_chunks / save_embeddings.

Verifies the bulk-write path (executemany + one bulk select) added to close
the N-round-trips-per-document bottleneck -- no live DB required, cursor is
a fake that just records calls.
"""
from __future__ import annotations

import sys
import types
import unittest
from contextlib import contextmanager
from unittest.mock import patch


def _stub_psycopg() -> None:
    if "psycopg" in sys.modules:
        return
    psycopg = types.ModuleType("psycopg")
    psycopg.connect = lambda *a, **k: None
    psycopg_sql = types.ModuleType("psycopg.sql")
    psycopg_types = types.ModuleType("psycopg.types")
    psycopg_types_json = types.ModuleType("psycopg.types.json")
    psycopg_types_json.Json = lambda obj, dumps=None: obj
    psycopg_types.json = psycopg_types_json
    psycopg.sql = psycopg_sql
    psycopg.types = psycopg_types
    sys.modules.update({
        "psycopg": psycopg, "psycopg.sql": psycopg_sql,
        "psycopg.types": psycopg_types, "psycopg.types.json": psycopg_types_json,
    })
    psycopg_pool = types.ModuleType("psycopg_pool")
    psycopg_pool.ConnectionPool = object
    sys.modules["psycopg_pool"] = psycopg_pool


_stub_psycopg()

from aryx.models import ChunkEmbedding, DocumentChunk, SourceRef  # noqa: E402
from aryx.store.chunk_store import ChunkStore  # noqa: E402


class _FakeCursor:
    """Records execute/executemany calls; fetchall returns a preset id map."""

    def __init__(self) -> None:
        self.executemany_calls: list[tuple[str, list]] = []
        self.execute_calls: list[tuple[str, object]] = []
        self._fetchall_result: list[tuple] = []

    def executemany(self, sql: str, rows: list) -> None:
        self.executemany_calls.append((sql, list(rows)))

    def execute(self, sql: str, params: object = None) -> None:
        self.execute_calls.append((sql, params))

    def fetchall(self) -> list[tuple]:
        return self._fetchall_result

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_: object) -> None:
        pass


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def __enter__(self) -> "_FakeConn":
        return self

    def __exit__(self, *_: object) -> None:
        pass


class _FakePool:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    @contextmanager
    def connection(self):
        yield _FakeConn(self._cursor)


def _store(cursor: _FakeCursor) -> ChunkStore:
    store = ChunkStore.__new__(ChunkStore)
    store._pool = _FakePool(cursor)
    return store


class TestSaveChunks(unittest.TestCase):
    """save_chunks must use one executemany + one bulk select, not a per-row loop."""

    def _chunks(self, n: int) -> list[DocumentChunk]:
        source = SourceRef(system="file", dataset="doc.pdf", record_id="hash")
        return [
            DocumentChunk(doc_id="hash", chunk_index=i, text=f"chunk {i}",
                          char_start=i * 10, char_end=i * 10 + 10, source=source)
            for i in range(n)
        ]

    def test_single_executemany_call_regardless_of_chunk_count(self) -> None:
        cur = _FakeCursor()
        cur._fetchall_result = [(100 + i, i) for i in range(5)]
        with patch("aryx.store.chunk_store.load", return_value="SQL"):
            ids = _store(cur).save_chunks(1, self._chunks(5))
        self.assertEqual(len(cur.executemany_calls), 1)
        self.assertEqual(len(cur.executemany_calls[0][1]), 5)
        self.assertEqual(ids, [100, 101, 102, 103, 104])

    def test_ids_mapped_by_chunk_index_not_row_order(self) -> None:
        """fetchall may return rows in any order -- ids must map by chunk_index."""
        cur = _FakeCursor()
        cur._fetchall_result = [(203, 2), (201, 0), (202, 1)]  # scrambled order
        with patch("aryx.store.chunk_store.load", return_value="SQL"):
            ids = _store(cur).save_chunks(1, self._chunks(3))
        self.assertEqual(ids, [201, 202, 203])

    def test_empty_chunks_no_db_calls(self) -> None:
        cur = _FakeCursor()
        with patch("aryx.store.chunk_store.load", return_value="SQL"):
            ids = _store(cur).save_chunks(1, [])
        self.assertEqual(ids, [])
        self.assertEqual(cur.executemany_calls, [])
        self.assertEqual(cur.execute_calls, [])

    def test_select_called_with_doc_id_and_index_list(self) -> None:
        cur = _FakeCursor()
        cur._fetchall_result = [(100, 0), (101, 1)]
        with patch("aryx.store.chunk_store.load", return_value="SQL"):
            _store(cur).save_chunks(42, self._chunks(2))
        self.assertEqual(len(cur.execute_calls), 1)
        _, params = cur.execute_calls[0]
        self.assertEqual(params, (42, [0, 1]))


class TestSaveEmbeddings(unittest.TestCase):
    """save_embeddings must use one executemany call, not a per-row loop."""

    def _embeddings(self, n: int) -> list[ChunkEmbedding]:
        return [
            ChunkEmbedding(chunk_index=i, doc_id="hash", model_id="m", dim=3,
                          vector=[0.1, 0.2, 0.3])
            for i in range(n)
        ]

    def test_single_executemany_call_regardless_of_count(self) -> None:
        cur = _FakeCursor()
        with patch("aryx.store.chunk_store.load", return_value="SQL"):
            _store(cur).save_embeddings([10, 11, 12], self._embeddings(3))
        self.assertEqual(len(cur.executemany_calls), 1)
        self.assertEqual(len(cur.executemany_calls[0][1]), 3)

    def test_vector_serialized_as_bracketed_string(self) -> None:
        cur = _FakeCursor()
        with patch("aryx.store.chunk_store.load", return_value="SQL"):
            _store(cur).save_embeddings([10], self._embeddings(1))
        row = cur.executemany_calls[0][1][0]
        self.assertEqual(row, (10, "m", 3, "[0.1,0.2,0.3]"))

    def test_empty_is_noop(self) -> None:
        cur = _FakeCursor()
        with patch("aryx.store.chunk_store.load", return_value="SQL"):
            _store(cur).save_embeddings([], [])
        self.assertEqual(cur.executemany_calls, [])


if __name__ == "__main__":
    unittest.main()
