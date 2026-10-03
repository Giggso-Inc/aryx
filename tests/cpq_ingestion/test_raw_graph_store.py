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
        store = get_raw_graph_store(50, "catalog", dsn="unused", graph_url="redis://localhost:6379")
    mock_db.return_value.select_graph.assert_called_once_with(raw_ws_graph(50, "catalog"))
    assert store is not None


def test_falkordb_raw_graph_uses_distinct_graph_name_from_curated():
    from aryx.naming import ws_graph

    assert raw_ws_graph(50, "catalog") != ws_graph(50)
    assert raw_ws_graph(50, "catalog") == "aryx_raw_ws_50_catalog"


def test_write_raw_graph_calls_clear_then_full_rebuild_batches_on_falkordb(monkeypatch):
    """Also covers Raven review H1: full_rebuild=True must be passed on both
    batch calls (verified via the actual call kwargs, not just query text —
    FalkorDB's batch mixin accepts full_rebuild for call-site parity with
    Oracle but always issues MERGE regardless, so query text alone wouldn't
    prove the flag was passed)."""
    monkeypatch.delenv("ARYX_GRAPH_BACKEND", raising=False)
    monkeypatch.delenv("ARYX_OCI_MODE", raising=False)
    with patch("aryx.graph.falkor_store.FalkorStore.add_entities_batch") as mock_entities, \
         patch("aryx.graph.falkor_store.FalkorStore.add_relationships_batch") as mock_rels, \
         patch("aryx.graph.falkor_store.FalkorDB") as mock_db:
        # write_raw_graph now reports the batch calls' ACTUAL return values
        # (PR #425 review fix -- previously it always reported
        # len(projection.nodes)/len(projection.edges) regardless of what
        # was really written), so these mocks must return realistic counts
        # for result.nodes_written/edges_written to mean anything here.
        mock_entities.return_value = 2
        mock_rels.return_value = 1
        mock_db.return_value.select_graph.return_value = MagicMock()
        result = write_raw_graph(
            _sample_projection(), workspace_id=50, source_key="catalog",
            dsn="unused", graph_url="redis://localhost:6379",
        )

    mock_entities.assert_called_once()
    assert mock_entities.call_args.kwargs.get("full_rebuild") is True
    mock_rels.assert_called_once()
    assert mock_rels.call_args.kwargs.get("full_rebuild") is True
    assert result.nodes_written == 2
    assert result.edges_written == 1
    assert result.backend == "falkordb"
    assert result.graph_ref == "graph=aryx_raw_ws_50_catalog"


def test_write_raw_graph_skips_relationships_batch_when_already_cancelled(monkeypatch):
    """PR #425 review: should_stop is checked again right before the
    relationships batch (a cancel can land either before this function
    starts or partway through the entities batch), and if it already
    fired, add_relationships_batch must never even be called -- not called
    and short-circuited internally, not called at all -- since starting a
    batch already known to be cancelled is pure wasted connection/setup
    overhead for a result that will immediately stop anyway."""
    monkeypatch.delenv("ARYX_GRAPH_BACKEND", raising=False)
    monkeypatch.delenv("ARYX_OCI_MODE", raising=False)
    with patch("aryx.graph.falkor_store.FalkorStore.add_entities_batch") as mock_entities, \
         patch("aryx.graph.falkor_store.FalkorStore.add_relationships_batch") as mock_rels, \
         patch("aryx.graph.falkor_store.FalkorDB") as mock_db:
        mock_entities.return_value = 0  # as if should_stop fired mid-entities-batch
        mock_db.return_value.select_graph.return_value = MagicMock()
        result = write_raw_graph(
            _sample_projection(), workspace_id=50, source_key="catalog",
            dsn="unused", graph_url="redis://localhost:6379",
            should_stop=lambda: True,
        )

    mock_entities.assert_called_once()  # entities is always attempted; should_stop is checked inside its own loop
    mock_rels.assert_not_called()
    assert result.nodes_written == 0
    assert result.edges_written == 0


def test_write_raw_graph_clears_before_writing_on_falkordb(monkeypatch):
    monkeypatch.delenv("ARYX_GRAPH_BACKEND", raising=False)
    monkeypatch.delenv("ARYX_OCI_MODE", raising=False)
    with patch("aryx.graph.falkor_store.FalkorDB") as mock_db:
        mock_graph = MagicMock()
        mock_db.return_value.select_graph.return_value = mock_graph
        write_raw_graph(
            _sample_projection(), workspace_id=50, source_key="catalog",
            dsn="unused", graph_url="redis://localhost:6379",
        )
    mock_graph.delete.assert_called_once()  # FalkorStore.clear() calls graph.delete() directly
    query_calls = [c.args[0] for c in mock_graph.query.call_args_list]
    assert any("MERGE" in c for c in query_calls), "entity/relationship batches must be written"


def test_two_source_files_in_same_workspace_write_to_independent_falkordb_graphs():
    """Regression guard for M1: writing file A must not clear file B's raw graph."""
    with patch("aryx.graph.falkor_store.FalkorDB") as mock_db:
        graph_a, graph_b = MagicMock(), MagicMock()
        mock_db.return_value.select_graph.side_effect = [graph_a, graph_b]
        write_raw_graph(_sample_projection(), workspace_id=50, source_key="fileA",
                         dsn="unused", graph_url="redis://localhost:6379")
        write_raw_graph(_sample_projection(), workspace_id=50, source_key="fileB",
                         dsn="unused", graph_url="redis://localhost:6379")
    calls = [c.args[0] for c in mock_db.return_value.select_graph.call_args_list]
    assert calls == ["aryx_raw_ws_50_fileA", "aryx_raw_ws_50_fileB"]
    # fileB's write must only ever touch its own graph object, never fileA's.
    graph_a.delete.assert_called_once()
    graph_b.delete.assert_called_once()


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
        store = get_raw_graph_store(50, "catalog", dsn="oracle://fake", graph_url="unused")

    assert isinstance(store, OracleGraphStore)
    offset = get_cpq_ingestion_settings().cpq_raw_workspace_offset
    assert store._workspace_id == raw_workspace_id(50, offset, "catalog")


def test_oracle_raw_workspace_id_is_offset_from_curated():
    offset = get_cpq_ingestion_settings().cpq_raw_workspace_offset
    assert raw_workspace_id(50, offset, "catalog") != 50


def test_oracle_write_passes_full_rebuild_true(monkeypatch):
    """Raven review H1: on Oracle, full_rebuild=True is what switches
    merge_graph_vertex/merge_graph_edge (MERGE) to insert_graph_vertex/
    insert_graph_edge (plain INSERT) -- the documented fix for a
    live-confirmed 180+ second MERGE executemany() hang per batch."""
    monkeypatch.setenv("ARYX_GRAPH_BACKEND", "oci_graph")
    OracleGraphStore = _load_oracle_graph_store_class()
    fake_pool = _FakePool()

    with patch("aryx.store.oracle_pool.get_oracle_pool", return_value=fake_pool), \
         patch.object(OracleGraphStore, "clear"), \
         patch.object(OracleGraphStore, "add_entities_batch") as mock_entities, \
         patch.object(OracleGraphStore, "add_relationships_batch") as mock_rels:
        write_raw_graph(
            _sample_projection(), workspace_id=50, source_key="catalog",
            dsn="oracle://fake", graph_url="unused",
        )

    mock_entities.assert_called_once()
    assert mock_entities.call_args.kwargs.get("full_rebuild") is True
    mock_rels.assert_called_once()
    assert mock_rels.call_args.kwargs.get("full_rebuild") is True


def test_two_source_files_in_same_workspace_resolve_to_different_oracle_workspace_ids():
    """Regression guard for M1 on the Oracle backend."""
    offset = get_cpq_ingestion_settings().cpq_raw_workspace_offset
    id_a = raw_workspace_id(50, offset, "fileA")
    id_b = raw_workspace_id(50, offset, "fileB")
    assert id_a != id_b
