"""raw_graph.store — backend dispatch and write calls, fully mocked.

No live Oracle ADB or FalkorDB required. FalkorDB is mocked the same way
tests/test_falkor_isolated_marking.py does (patch aryx.graph.falkor_store.
FalkorDB); OracleGraphStore is constructed the same way
tests/test_oracle_pool.py does (bypass __init__, hand it a fake pool),
since it needs a real oracledb-shaped connection object that this local
dev environment (Postgres + FalkorDB only) does not have.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
from aryx.cpq_ingestion.naming import raw_workspace_id, raw_ws_graph
from aryx.cpq_ingestion.raw_graph.models import RawEdge, RawGraphProjection, RawNode
from aryx.cpq_ingestion.raw_graph.store import get_raw_graph_store, write_raw_graph


@pytest.fixture(autouse=True)
def _clear_settings_caches():
    from aryx.config import get_settings

    get_settings.cache_clear()
    get_cpq_ingestion_settings.cache_clear()
    yield
    get_settings.cache_clear()
    get_cpq_ingestion_settings.cache_clear()


def _sample_projection() -> RawGraphProjection:
    return RawGraphProjection(
        nodes=[
            RawNode(id=1, tag="Accounts", properties={}),
            RawNode(id=2, tag="Account", properties={"Id": "001AC"}),
        ],
        edges=[RawEdge(source_id=1, target_id=2, name="CONTAINS")],
    )


def test_falkordb_backend_selected_by_default(monkeypatch):
    monkeypatch.delenv("ARYX_GRAPH_BACKEND", raising=False)
    monkeypatch.delenv("ARYX_OCI_MODE", raising=False)
    with patch("aryx.graph.falkor_store.FalkorDB") as mock_db:
        mock_db.return_value.select_graph.return_value = MagicMock()
        store = get_raw_graph_store(50, dsn="unused", graph_url="redis://localhost:6379")
    mock_db.return_value.select_graph.assert_called_once_with(raw_ws_graph(50))
    assert store is not None


def test_falkordb_raw_graph_uses_distinct_graph_name_from_curated():
    from aryx.naming import ws_graph

    assert raw_ws_graph(50) != ws_graph(50)
    assert raw_ws_graph(50) == "aryx_raw_ws_50"


def test_write_raw_graph_calls_clear_then_batches_on_falkordb(monkeypatch):
    monkeypatch.delenv("ARYX_GRAPH_BACKEND", raising=False)
    monkeypatch.delenv("ARYX_OCI_MODE", raising=False)
    with patch("aryx.graph.falkor_store.FalkorDB") as mock_db:
        mock_graph = MagicMock()
        mock_db.return_value.select_graph.return_value = mock_graph
        result = write_raw_graph(
            _sample_projection(), workspace_id=50, dsn="unused", graph_url="redis://localhost:6379",
        )

    mock_graph.delete.assert_called_once()  # FalkorStore.clear() calls graph.delete() directly
    query_calls = [c.args[0] for c in mock_graph.query.call_args_list]
    assert any("MERGE" in c for c in query_calls), "entity/relationship batches must be written"
    assert result.nodes_written == 2
    assert result.edges_written == 1
    assert result.backend == "falkordb"
    assert result.graph_ref == "graph=aryx_raw_ws_50"


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, object]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> None:
        self.executed.append((sql, params))

    def executemany(self, sql: str, rows: object) -> None:
        self.executed.append((sql, rows))


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def execute(self, sql: str, params: object = None) -> None:
        self._cursor.execute(sql, params)

    def commit(self) -> None:
        return None


class _FakePool:
    def __init__(self) -> None:
        self.cursor = _FakeCursor()
        self.conn = _FakeConn(self.cursor)

    @contextmanager
    def connection(self):
        yield self.conn


def _load_oracle_graph_store_class():
    """Import OracleGraphStore the way tests/test_oracle_pool.py does — stub
    oracledb first so the real driver need not be installed/connectable."""
    import sys
    import types

    if "oracledb" not in sys.modules:
        stub = types.ModuleType("oracledb")
        stub.connect = lambda *a, **k: None  # noqa: ARG005
        sys.modules["oracledb"] = stub
    from aryx.graph.oracle_graph_store import OracleGraphStore

    return OracleGraphStore


def test_oracle_backend_selected_when_graph_backend_is_oci_graph(monkeypatch):
    monkeypatch.setenv("ARYX_GRAPH_BACKEND", "oci_graph")
    OracleGraphStore = _load_oracle_graph_store_class()

    fake_pool = _FakePool()
    with patch("aryx.store.oracle_pool.get_oracle_pool", return_value=fake_pool):
        store = get_raw_graph_store(50, dsn="oracle://fake", graph_url="unused")

    assert isinstance(store, OracleGraphStore)
    assert store._workspace_id == raw_workspace_id(50, get_cpq_ingestion_settings().cpq_raw_workspace_offset)


def test_oracle_raw_workspace_id_is_offset_from_curated():
    offset = get_cpq_ingestion_settings().cpq_raw_workspace_offset
    assert raw_workspace_id(50, offset) == 50 + offset
    assert raw_workspace_id(50, offset) != 50
