"""Tests for scalability bottleneck fixes P1–P7.

Covers:
  - Config: new fields have correct defaults and read from ARYX_* env vars
  - P1: list_entities/provenance/relationships use fetchmany (streaming cursor)
  - P2: match_entities returns dicts; engine calls match_entities per rule
  - P3: MultiKeyBlocker reads max_block_size from config; cap enforced
  - P4: _get_executor creates ThreadPoolExecutor with worker_threads; singleton
  - P5: GraphReader.find_entities cap reads from graph_query_limit config
  - P6: run_pipeline resolves max_relate_pairs from config when max_pairs=None
  - P7: apply_transitive caps hops at transitive_max_depth from config

Run:
    PYTHONPATH=src python -m pytest tests/test_scalability_fixes.py -v
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Module-level stubs — must come first, before any aryx imports.
# psycopg and related packages are only in the Docker container, not the
# host Python env used by the test runner.
# ---------------------------------------------------------------------------
for _mod in (
    "psycopg",
    "psycopg.types",
    "psycopg.types.json",
    "psycopg.rows",
    "pgvector",
    "pgvector.psycopg",
    "falkordb",
    "openai",
    "anthropic",
    "presidio_analyzer",
    "presidio_anonymizer",
    "pymupdf",
    "pymupdf4llm",
    "docx",
    "pptx",
    "PIL",
    "PIL.Image",
):
    sys.modules.setdefault(_mod, MagicMock())

# psycopg_pool needs ConnectionPool to be an importable name on the mock
_mock_cp = MagicMock()
sys.modules.setdefault("psycopg_pool", MagicMock(ConnectionPool=_mock_cp))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db_mock(fetchall_rows=None, fetchmany_batches=None):
    """Return (pool, conn, cursor) mocks wired as context managers.

    fetchall_rows:    list of rows returned by cursor.fetchall()
    fetchmany_batches: list of batches; each call to cursor.fetchmany() pops one.
                       The last batch should be [] to stop the while-loop.
    """
    mock_cur = MagicMock()
    if fetchall_rows is not None:
        mock_cur.fetchall.return_value = fetchall_rows
    if fetchmany_batches is not None:
        mock_cur.fetchmany.side_effect = fetchmany_batches

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    mock_pool = MagicMock()
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    return mock_pool, mock_conn, mock_cur


# ---------------------------------------------------------------------------
# Config — new fields
# ---------------------------------------------------------------------------

class TestConfigNewFields:
    """Config: five new Settings fields exist with correct defaults."""

    def test_all_new_fields_present(self):
        from aryx.config import Settings
        fields = Settings.model_fields
        assert "max_block_size" in fields
        assert "graph_query_limit" in fields
        assert "max_relate_pairs" in fields
        assert "transitive_max_depth" in fields
        assert "worker_threads" in fields

    def test_default_values(self):
        from aryx.config import Settings
        fields = Settings.model_fields
        assert fields["max_block_size"].default == 5000
        assert fields["graph_query_limit"].default == 500
        assert fields["max_relate_pairs"].default == 50
        assert fields["transitive_max_depth"].default == 4
        assert fields["worker_threads"].default == 4

    def test_env_override_max_block_size(self, monkeypatch: pytest.MonkeyPatch):
        from aryx.config import Settings
        monkeypatch.setenv("ARYX_MAX_BLOCK_SIZE", "9999")
        s = Settings(_env_file=None)
        assert s.max_block_size == 9999

    def test_env_override_graph_query_limit(self, monkeypatch: pytest.MonkeyPatch):
        from aryx.config import Settings
        monkeypatch.setenv("ARYX_GRAPH_QUERY_LIMIT", "1000")
        s = Settings(_env_file=None)
        assert s.graph_query_limit == 1000

    def test_env_override_max_relate_pairs(self, monkeypatch: pytest.MonkeyPatch):
        from aryx.config import Settings
        monkeypatch.setenv("ARYX_MAX_RELATE_PAIRS", "200")
        s = Settings(_env_file=None)
        assert s.max_relate_pairs == 200

    def test_env_override_transitive_max_depth(self, monkeypatch: pytest.MonkeyPatch):
        from aryx.config import Settings
        monkeypatch.setenv("ARYX_TRANSITIVE_MAX_DEPTH", "8")
        s = Settings(_env_file=None)
        assert s.transitive_max_depth == 8

    def test_env_override_worker_threads(self, monkeypatch: pytest.MonkeyPatch):
        from aryx.config import Settings
        monkeypatch.setenv("ARYX_WORKER_THREADS", "8")
        s = Settings(_env_file=None)
        assert s.worker_threads == 8


# ---------------------------------------------------------------------------
# P1 — entity_store streaming cursor
# ---------------------------------------------------------------------------

class TestEntityStoreStreaming:
    """P1: list_entities/provenance/relationships use fetchmany not fetchall."""

    def test_list_entities_uses_fetchmany(self):
        pool, _, cur = _make_db_mock(
            fetchmany_batches=[
                [(1, "Customer", {"name": "Acme"})],
                [],
            ]
        )
        with patch("aryx.store.entity_store.get_pool", return_value=pool), \
             patch("aryx.store.entity_store.get_settings") as mock_cfg:
            mock_cfg.return_value.batch_size = 500
            from aryx.store.entity_store import EntityStore
            result = EntityStore("dsn", 1).list_entities()

        cur.fetchmany.assert_called()
        cur.fetchall.assert_not_called()
        assert result == [(1, "Customer", {"name": "Acme"})]

    def test_list_entities_returns_tuples(self):
        pool, _, cur = _make_db_mock(
            fetchmany_batches=[
                [(10, "Vendor", {"city": "NYC"}), (11, "Vendor", {"city": "LA"})],
                [],
            ]
        )
        with patch("aryx.store.entity_store.get_pool", return_value=pool), \
             patch("aryx.store.entity_store.get_settings") as mock_cfg:
            mock_cfg.return_value.batch_size = 500
            from aryx.store.entity_store import EntityStore
            result = EntityStore("dsn", 1).list_entities()

        assert len(result) == 2
        assert result[0] == (10, "Vendor", {"city": "NYC"})

    def test_list_members_provenance_uses_fetchmany(self):
        pool, _, cur = _make_db_mock(
            fetchmany_batches=[
                [(1, "crm", "contacts", "rec-42")],
                [],
            ]
        )
        with patch("aryx.store.entity_store.get_pool", return_value=pool), \
             patch("aryx.store.entity_store.get_settings") as mock_cfg:
            mock_cfg.return_value.batch_size = 500
            from aryx.store.entity_store import EntityStore
            result = EntityStore("dsn", 1).list_members_provenance()

        cur.fetchmany.assert_called()
        cur.fetchall.assert_not_called()
        assert result == [(1, "crm", "contacts", "rec-42")]

    def test_list_relationships_uses_fetchmany(self):
        pool, _, cur = _make_db_mock(
            fetchmany_batches=[
                [(1, 2, "WORKS_AT")],
                [],
            ]
        )
        with patch("aryx.store.entity_store.get_pool", return_value=pool), \
             patch("aryx.store.entity_store.get_settings") as mock_cfg:
            mock_cfg.return_value.batch_size = 500
            from aryx.store.entity_store import EntityStore
            result = EntityStore("dsn", 1).list_relationships()

        cur.fetchmany.assert_called()
        cur.fetchall.assert_not_called()
        assert result == [(1, 2, "WORKS_AT")]

    def test_list_entities_batches_across_pages(self):
        """fetchmany is called repeatedly until empty batch signals end."""
        pool, _, cur = _make_db_mock(
            fetchmany_batches=[
                [(1, "A", {}), (2, "A", {})],   # batch 1
                [(3, "A", {})],                  # batch 2
                [],                              # end of stream
            ]
        )
        with patch("aryx.store.entity_store.get_pool", return_value=pool), \
             patch("aryx.store.entity_store.get_settings") as mock_cfg:
            mock_cfg.return_value.batch_size = 2
            from aryx.store.entity_store import EntityStore
            result = EntityStore("dsn", 1).list_entities()

        assert cur.fetchmany.call_count == 3
        assert len(result) == 3


# ---------------------------------------------------------------------------
# P2 — match_entities SQL pushdown
# ---------------------------------------------------------------------------

class TestMatchEntities:
    """P2: match_entities returns dicts; filters pushed to SQL."""

    def _match_pool(self, rows=None):
        """Helper: pool mock with fetchmany_batches for match_entities."""
        batches = ([rows, []] if rows else [[]])
        pool, _, cur = _make_db_mock(fetchmany_batches=batches)
        return pool, cur

    def test_match_entities_returns_dicts(self):
        pool, cur = self._match_pool([(1, "Customer", {"revenue": 5_000_000})])
        with patch("aryx.store.entity_store.get_pool", return_value=pool), \
             patch("aryx.store.entity_store.get_settings") as mock_cfg:
            mock_cfg.return_value.batch_size = 500
            from aryx.store.entity_store import EntityStore
            result = EntityStore("dsn", 1).match_entities(
                {"type": "Customer", "attr": "revenue", "op": ">", "value": 1_000_000}
            )

        assert result == [{"id": 1, "type": "Customer",
                           "attributes": {"revenue": 5_000_000}}]

    def test_match_entities_uses_fetchmany_not_fetchall(self):
        """W4 fix: match_entities must stream via fetchmany, not fetchall."""
        pool, cur = self._match_pool()
        with patch("aryx.store.entity_store.get_pool", return_value=pool), \
             patch("aryx.store.entity_store.get_settings") as mock_cfg:
            mock_cfg.return_value.batch_size = 500
            from aryx.store.entity_store import EntityStore
            EntityStore("dsn", 1).match_entities({"type": "X"})

        cur.fetchmany.assert_called()
        cur.fetchall.assert_not_called()

    def test_match_entities_cursor_name_includes_workspace(self):
        """W3 fix: cursor name is workspace-scoped to prevent collisions."""
        pool, _, cur = _make_db_mock(fetchmany_batches=[[]])
        with patch("aryx.store.entity_store.get_pool", return_value=pool), \
             patch("aryx.store.entity_store.get_settings") as mock_cfg:
            mock_cfg.return_value.batch_size = 500
            from aryx.store.entity_store import EntityStore
            EntityStore("dsn", workspace_id=7).match_entities({})

        # conn.cursor("match_entities_cur_7") must have been called
        _, conn, _ = pool, None, None
        cursor_name = pool.connection.return_value.__enter__.return_value.cursor.call_args[0][0]
        assert "7" in cursor_name

    def test_match_entities_passes_type_and_attr_to_sql(self):
        pool, cur = self._match_pool()
        with patch("aryx.store.entity_store.get_pool", return_value=pool), \
             patch("aryx.store.entity_store.get_settings") as mock_cfg:
            mock_cfg.return_value.batch_size = 500
            from aryx.store.entity_store import EntityStore
            EntityStore("dsn", 1).match_entities(
                {"type": "Vendor", "attr": "country"}
            )

        execute_call = cur.execute.call_args
        params = execute_call[0][1]  # positional: (sql, params)
        # workspace_id, type (x2), attr (x2) — from select_entities_matching.sql
        assert "Vendor" in params
        assert "country" in params

    def test_match_entities_passes_null_when_no_type(self):
        """When when-clause has no type, None is passed so SQL skips the filter."""
        pool, cur = self._match_pool()
        with patch("aryx.store.entity_store.get_pool", return_value=pool), \
             patch("aryx.store.entity_store.get_settings") as mock_cfg:
            mock_cfg.return_value.batch_size = 500
            from aryx.store.entity_store import EntityStore
            EntityStore("dsn", 1).match_entities(
                {"attr": "status", "op": "==", "value": "active"}
            )

        params = cur.execute.call_args[0][1]
        assert None in params  # type placeholder is NULL

    def test_match_entities_empty_when_returns_all_workspace(self):
        """Empty when-clause passes None for both type and attr (no filters)."""
        pool, cur = self._match_pool()
        with patch("aryx.store.entity_store.get_pool", return_value=pool), \
             patch("aryx.store.entity_store.get_settings") as mock_cfg:
            mock_cfg.return_value.batch_size = 500
            from aryx.store.entity_store import EntityStore
            EntityStore("dsn", 1).match_entities({})

        params = cur.execute.call_args[0][1]
        assert params.count(None) >= 2  # both type and attr are NULL


class TestEngineUsesMatchEntities:
    """P2: evaluate_workspace calls match_entities per rule, not list_entities."""

    def test_engine_calls_match_entities_not_list_entities(self):
        rules = [
            {
                "name": "platinum", "enabled": True,
                "when": {"type": "Customer", "attr": "revenue",
                         "op": ">", "value": 1_000_000},
                "then": {"set_label": "Platinum"},
            }
        ]
        mock_rules_store = MagicMock()
        mock_rules_store.list_.return_value = rules

        mock_estore = MagicMock()
        mock_estore.match_entities.return_value = []

        mock_bumps = MagicMock()
        mock_graph = MagicMock()

        mock_cfg = MagicMock()
        mock_cfg.rdb_dsn = "postgresql://x"
        mock_cfg.graph_url = "redis://x"

        with patch("aryx.reasoning.engine.get_settings", return_value=mock_cfg), \
             patch("aryx.reasoning.engine.RuleStore",
                   side_effect=[mock_rules_store, mock_bumps]), \
             patch("aryx.reasoning.engine.EntityStore", return_value=mock_estore), \
             patch("aryx.reasoning.engine.FalkorStore", return_value=mock_graph), \
             patch("aryx.reasoning.engine.ws_graph", return_value="ws_1"):
            from aryx.reasoning.engine import evaluate_workspace
            evaluate_workspace(workspace_id=1)

        mock_estore.match_entities.assert_called_once_with(rules[0]["when"])
        mock_estore.list_entities.assert_not_called()

    def test_engine_fires_on_matching_entity(self):
        """_match() receives dict from match_entities and fires correctly."""
        rules = [
            {
                "name": "big_revenue", "enabled": True,
                "when": {"type": "Customer", "attr": "revenue",
                         "op": ">", "value": 1_000_000},
                "then": {"set_label": "Platinum"},
            }
        ]
        # match_entities returns a dict — the format _match() expects
        matching_entity = {"id": 42, "type": "Customer",
                           "attributes": {"revenue": 5_000_000}}

        mock_rules_store = MagicMock()
        mock_rules_store.list_.return_value = rules
        mock_estore = MagicMock()
        mock_estore.match_entities.return_value = [matching_entity]
        mock_bumps = MagicMock()
        mock_graph = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.rdb_dsn = "postgresql://x"
        mock_cfg.graph_url = "redis://x"

        with patch("aryx.reasoning.engine.get_settings", return_value=mock_cfg), \
             patch("aryx.reasoning.engine.RuleStore",
                   side_effect=[mock_rules_store, mock_bumps]), \
             patch("aryx.reasoning.engine.EntityStore", return_value=mock_estore), \
             patch("aryx.reasoning.engine.FalkorStore", return_value=mock_graph), \
             patch("aryx.reasoning.engine.ws_graph", return_value="ws_1"):
            from aryx.reasoning.engine import evaluate_workspace
            result = evaluate_workspace(workspace_id=1)

        assert result["total_fires"] == 1
        assert result["per_rule"]["big_revenue"] == 1

    def test_engine_finally_safe_when_falkorstore_raises(self):
        """B3 fix: NameError must NOT mask the original exception when FalkorStore raises."""
        rules = [{"name": "r1", "enabled": True, "when": {}, "then": {}}]
        mock_rules_store = MagicMock()
        mock_rules_store.list_.return_value = rules
        mock_bumps = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.rdb_dsn = "postgresql://x"
        mock_cfg.graph_url = "redis://x"

        with patch("aryx.reasoning.engine.get_settings", return_value=mock_cfg), \
             patch("aryx.reasoning.engine.RuleStore",
                   side_effect=[mock_rules_store, mock_bumps]), \
             patch("aryx.reasoning.engine.EntityStore"), \
             patch("aryx.reasoning.engine.FalkorStore",
                   side_effect=ConnectionError("graph unreachable")), \
             patch("aryx.reasoning.engine.ws_graph", return_value="ws_1"):
            from aryx.reasoning.engine import evaluate_workspace
            with pytest.raises(ConnectionError, match="graph unreachable"):
                evaluate_workspace(workspace_id=1)
        # If B3 were still present the finally block would raise NameError instead

    def test_apply_edge_rejects_invalid_relationship_name(self):
        """W5 fix: _apply_edge raises ValueError on names that would inject Cypher."""
        mock_graph = MagicMock()
        with patch("aryx.reasoning.engine.FalkorStore", return_value=mock_graph):
            from aryx.reasoning.engine import _apply_edge
            with pytest.raises(ValueError, match=r"\[A-Z0-9_\]\+"):
                _apply_edge(mock_graph, 1, "bad-name]MATCH", "T", "n")
            with pytest.raises(ValueError):
                _apply_edge(mock_graph, 1, "has space", "T", "n")

    def test_apply_edge_accepts_valid_relationship_name(self):
        """Valid uppercase identifiers must not be rejected."""
        mock_graph = MagicMock()
        with patch("aryx.reasoning.engine.FalkorStore", return_value=mock_graph):
            from aryx.reasoning.engine import _apply_edge
            _apply_edge(mock_graph, 1, "TIER_MEMBER", "Tier", "Gold")
            _apply_edge(mock_graph, 1, "part_of", "Group", "HQ")  # lower → upper normalised
        assert mock_graph.run.call_count == 2

    def test_invalid_relationship_name_skips_rule_not_evaluation(self):
        """ValueError from invalid relationship name must not abort remaining rules.

        A rule with then.add_relationship='reports-to' (hyphen) raises ValueError
        from _apply_edge. The rule loop must catch it, log a warning, record
        fires=0 for that rule, and continue evaluating subsequent rules.
        """
        rules = [
            {
                "name": "bad_rel", "enabled": True,
                "when": {"type": "Person", "attr": "dept", "op": "==", "value": "eng"},
                "then": {"add_relationship": "reports-to"},  # hyphen → ValueError
            },
            {
                "name": "good_label", "enabled": True,
                "when": {"type": "Customer", "attr": "tier", "op": "==", "value": "gold"},
                "then": {"set_label": "Gold"},
            },
        ]
        mock_rules_store = MagicMock()
        mock_rules_store.list_.return_value = rules

        mock_estore = MagicMock()
        mock_estore.match_entities.side_effect = lambda when: (
            [{"id": 1, "type": "Person", "attributes": {"dept": "eng"}}]
            if when.get("type") == "Person"
            else [{"id": 2, "type": "Customer", "attributes": {"tier": "gold"}}]
        )

        mock_bumps = MagicMock()
        mock_graph = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.rdb_dsn = "postgresql://x"
        mock_cfg.graph_url = "redis://x"

        with patch("aryx.reasoning.engine.get_settings", return_value=mock_cfg), \
             patch("aryx.reasoning.engine.RuleStore",
                   side_effect=[mock_rules_store, mock_bumps]), \
             patch("aryx.reasoning.engine.EntityStore", return_value=mock_estore), \
             patch("aryx.reasoning.engine.FalkorStore", return_value=mock_graph), \
             patch("aryx.reasoning.engine.ws_graph", return_value="ws_1"):
            from aryx.reasoning.engine import evaluate_workspace
            result = evaluate_workspace(workspace_id=1)

        # bad_rel caught as ValueError → fires=0; good_label continues → fires=1
        assert result["per_rule"]["bad_rel"] == 0
        assert result["per_rule"]["good_label"] == 1
        assert result["total_fires"] == 1
        assert result["rules_evaluated"] == 2


# ---------------------------------------------------------------------------
# P3 — MultiKeyBlocker reads from config
# ---------------------------------------------------------------------------

class TestBlockerConfig:
    """P3: MultiKeyBlocker.max_block_size reads from ARYX_MAX_BLOCK_SIZE."""

    def test_explicit_value_overrides_config(self):
        from aryx.resolution.blocking import MultiKeyBlocker
        b = MultiKeyBlocker(max_block_size=99)
        assert b.max_block_size == 99

    def test_default_reads_config(self):
        """MultiKeyBlocker() with no arg reads max_block_size from get_settings()."""
        with patch("aryx.resolution.blocking.get_settings") as mock_cfg:
            mock_cfg.return_value.max_block_size = 777
            from aryx.resolution.blocking import MultiKeyBlocker
            b = MultiKeyBlocker()
        assert b.max_block_size == 777

    def test_block_drops_oversized_block(self):
        """Blocks exceeding max_block_size are silently dropped."""
        from aryx.models import ResolutionRecord
        from aryx.resolution.blocking import MultiKeyBlocker

        # Three records with identical text → same blocking keys → block size 3
        recs = [
            ResolutionRecord(record_id=i, text="john smith",
                             payload={"name": "john smith"})
            for i in range(3)
        ]
        b = MultiKeyBlocker(max_block_size=2)
        result = b.block(recs)

        # All key families produce blocks of size 3 which exceeds cap of 2 → all dropped
        assert len(result) == 0, "every block should be dropped when over cap"

    def test_block_keeps_block_within_limit(self):
        """Blocks at or below max_block_size are kept."""
        from aryx.models import ResolutionRecord
        from aryx.resolution.blocking import MultiKeyBlocker

        recs = [
            ResolutionRecord(record_id=1, text="acme corp",
                             payload={"name": "acme corp"}),
            ResolutionRecord(record_id=2, text="globex inc",
                             payload={"name": "globex inc"}),
        ]
        b = MultiKeyBlocker(max_block_size=5000)
        result = b.block(recs)

        # Both records exist in the result under at least one key
        all_members = {m.record_id for v in result.values() for m in v}
        assert 1 in all_members
        assert 2 in all_members

    def test_block_cap_equals_size_keeps_block(self):
        """W1 complement: a block of exactly cap=3 is NOT dropped."""
        from aryx.models import ResolutionRecord
        from aryx.resolution.blocking import MultiKeyBlocker

        recs = [
            ResolutionRecord(record_id=i, text="john smith",
                             payload={"name": "john smith"})
            for i in range(3)
        ]
        b = MultiKeyBlocker(max_block_size=3)  # cap == block size → keep
        result = b.block(recs)

        all_members = {m.record_id for v in result.values() for m in v}
        assert len(all_members) == 3, "all records should appear when block size == cap"

    def test_classical_block_shim_passes_none_to_multi_key_blocker(self):
        """classical.block() with default None delegates to MultiKeyBlocker."""
        from aryx.resolution.classical import block
        import inspect
        sig = inspect.signature(block)
        assert sig.parameters["max_block_size"].default is None


# ---------------------------------------------------------------------------
# P4 — ThreadPoolExecutor worker
# ---------------------------------------------------------------------------

class TestThreadPoolExecutor:
    """P4: _get_executor returns a singleton ThreadPoolExecutor sized by config."""

    def _reset_executor(self):
        # Reset module-level executor singleton between tests
        import importlib
        import aryx.api.file_ingest_api as m
        m._executor = None

    def setup_method(self):
        self._reset_executor()

    def teardown_method(self):
        self._reset_executor()
        from aryx.config import get_settings
        get_settings.cache_clear()

    def test_executor_uses_worker_threads(self):
        """_get_executor() creates ThreadPoolExecutor with worker_threads from config."""
        with patch("aryx.api.file_ingest_api.get_settings") as mock_cfg:
            mock_cfg.return_value.worker_threads = 2
            from aryx.api.file_ingest_api import _get_executor
            executor = _get_executor()
        assert executor._max_workers == 2

    def test_executor_is_singleton(self):
        """Calling _get_executor() twice returns the same object."""
        with patch("aryx.api.file_ingest_api.get_settings") as mock_cfg:
            mock_cfg.return_value.worker_threads = 3
            from aryx.api.file_ingest_api import _get_executor
            e1 = _get_executor()
            e2 = _get_executor()
        assert e1 is e2

    def test_background_tasks_not_imported(self):
        """BackgroundTasks must no longer appear in file_ingest_api."""
        import pathlib
        src = (pathlib.Path(__file__).parent.parent / "src/aryx/api/file_ingest_api.py").read_text()
        assert "BackgroundTasks" not in src

    def test_executor_submit_not_add_task(self):
        """The endpoint submits work via executor.submit(), not BackgroundTasks."""
        import pathlib
        src = (pathlib.Path(__file__).parent.parent / "src/aryx/api/file_ingest_api.py").read_text()
        assert "_get_executor().submit(" in src

    def test_executor_lock_present(self):
        """B1 fix: _executor_lock must exist to prevent double-initialisation race."""
        import aryx.api.file_ingest_api as m
        assert hasattr(m, "_executor_lock")
        import threading
        assert isinstance(m._executor_lock, type(threading.Lock()))

    def test_submit_future_has_done_callback(self):
        """B2 fix: endpoint wires add_done_callback to the future returned by submit()."""
        import asyncio
        from unittest.mock import AsyncMock
        from fastapi import UploadFile

        mock_future = MagicMock()
        mock_executor = MagicMock()
        mock_executor.submit.return_value = mock_future

        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = "data.csv"
        mock_file.read = AsyncMock(return_value=b"id,name\n1,Alice")

        with patch("aryx.api.file_ingest_api._get_executor", return_value=mock_executor), \
             patch("aryx.api.file_ingest_api.get_settings") as mock_cfg, \
             patch("aryx.api.file_ingest_api.apply_migrations"), \
             patch("aryx.api.file_ingest_api.JobStore"):
            mock_cfg.return_value.rdb_dsn = "postgresql://x"
            from aryx.api.file_ingest_api import file_ingest_router
            router = file_ingest_router()
            handler = next(r for r in router.routes if "POST" in r.methods).endpoint
            asyncio.run(handler(
                files=[mock_file],
                ontology_type="Company",
                match_keys="name",
                fk_links="[]",
                workspace_id=1,
            ))

        mock_future.add_done_callback.assert_called_once()

    def test_run_files_jobstore_raises_no_nameerror(self):
        """B4 fix: JobStore() raising must not cause NameError in except/finally."""
        with patch("aryx.api.file_ingest_api.get_settings") as mock_cfg, \
             patch("aryx.api.file_ingest_api.JobStore",
                   side_effect=RuntimeError("DB down")):
            mock_cfg.return_value.rdb_dsn = "postgresql://x"
            from aryx.api.file_ingest_api import _run_files
            # Pre-fix: NameError from jobs.finish/jobs.close in except/finally.
            # Post-fix: logs warning and returns cleanly.
            _run_files([], "Company", [], [], "test-job-id", 1)


# ---------------------------------------------------------------------------
# P5 — GraphReader query cap from config
# ---------------------------------------------------------------------------

class TestGraphReaderCap:
    """P5: find_entities LIMIT reads from ARYX_GRAPH_QUERY_LIMIT."""

    def test_find_entities_limit_from_config(self, monkeypatch: pytest.MonkeyPatch):
        from aryx.config import get_settings
        get_settings.cache_clear()
        monkeypatch.setenv("ARYX_GRAPH_QUERY_LIMIT", "10")

        mock_graph = MagicMock()
        mock_graph.query.return_value.result_set = []

        try:
            with patch("aryx.graph.reader.FalkorDB") as MockDB, \
                 patch("aryx.graph.reader.get_settings") as mock_cfg:
                mock_cfg.return_value.graph_query_limit = 10
                MockDB.return_value.select_graph.return_value = mock_graph
                from aryx.graph.reader import GraphReader
                reader = GraphReader("redis://localhost:6379")
                reader.find_entities(limit=9999)  # request far more than cap

            call_args = mock_graph.query.call_args
            query_str = call_args[0][0]
            assert "LIMIT 10" in query_str
        finally:
            get_settings.cache_clear()

    def test_find_entities_limit_coerced_to_min_one(self, monkeypatch: pytest.MonkeyPatch):
        """Limit of 0 or negative is coerced to 1."""
        mock_graph = MagicMock()
        mock_graph.query.return_value.result_set = []

        with patch("aryx.graph.reader.FalkorDB") as MockDB, \
             patch("aryx.graph.reader.get_settings") as mock_cfg:
            mock_cfg.return_value.graph_query_limit = 500
            MockDB.return_value.select_graph.return_value = mock_graph
            from aryx.graph.reader import GraphReader
            reader = GraphReader("redis://localhost:6379")
            reader.find_entities(limit=0)

        query_str = mock_graph.query.call_args[0][0]
        assert "LIMIT 1" in query_str


# ---------------------------------------------------------------------------
# P6 — orchestrate max_relate_pairs from config
# ---------------------------------------------------------------------------

class TestOrchestratePairs:
    """P6: run_pipeline reads max_relate_pairs from config when max_pairs=None."""

    @staticmethod
    def _make_runner():
        """StageRunner mock where skip() returns False so all stages execute."""
        mock_runner = MagicMock()
        mock_runner.skip.return_value = False
        # stage() used as context manager — MagicMock handles __enter__/__exit__
        return mock_runner

    def test_max_pairs_resolved_from_config(self, monkeypatch: pytest.MonkeyPatch):
        from aryx.config import get_settings
        get_settings.cache_clear()
        monkeypatch.setenv("ARYX_MAX_RELATE_PAIRS", "25")

        captured: dict = {}

        def fake_relate(estore, broker, max_pairs):
            captured["max_pairs"] = max_pairs
            return 0

        mock_cfg = MagicMock()
        mock_cfg.rdb_dsn = "postgresql://x"
        mock_cfg.graph_url = "redis://x"
        mock_cfg.max_relate_pairs = 25
        mock_runner = self._make_runner()

        with patch("aryx.pipeline.orchestrate.get_settings", return_value=mock_cfg), \
             patch("aryx.pipeline.orchestrate._relate", side_effect=fake_relate), \
             patch("aryx.pipeline.orchestrate.discover", return_value=1), \
             patch("aryx.pipeline.orchestrate.resolve_run", return_value=5), \
             patch("aryx.pipeline.orchestrate.project_graph", return_value={}), \
             patch("aryx.pipeline.orchestrate.StageRunner", return_value=mock_runner), \
             patch("aryx.pipeline.orchestrate.StageTracker"), \
             patch("aryx.pipeline.orchestrate.PostgresStore"), \
             patch("aryx.pipeline.orchestrate.EntityStore"), \
             patch("aryx.pipeline.orchestrate.FalkorStore"), \
             patch("aryx.pipeline.orchestrate._build_type_ancestors", return_value={}), \
             patch("aryx.pipeline.orchestrate.ws_graph", return_value="ws_1"):
            from aryx.pipeline.orchestrate import run_pipeline
            run_pipeline(
                connector=MagicMock(), dsn="postgresql://x",
                system="sys", dataset="ds", ontology_type="T",
                match_keys=["name"], graph_url="redis://x",
                broker=MagicMock(), relate=True,
                # max_pairs intentionally omitted → should use config value
            )

        assert captured.get("max_pairs") == 25
        get_settings.cache_clear()

    def test_explicit_max_pairs_overrides_config(self, monkeypatch: pytest.MonkeyPatch):
        """Explicit max_pairs=10 bypasses config value of 25."""
        captured: dict = {}

        def fake_relate(estore, broker, max_pairs):
            captured["max_pairs"] = max_pairs
            return 0

        mock_cfg = MagicMock()
        mock_cfg.rdb_dsn = "postgresql://x"
        mock_cfg.graph_url = "redis://x"
        mock_cfg.max_relate_pairs = 25
        mock_runner = self._make_runner()

        with patch("aryx.pipeline.orchestrate.get_settings", return_value=mock_cfg), \
             patch("aryx.pipeline.orchestrate._relate", side_effect=fake_relate), \
             patch("aryx.pipeline.orchestrate.discover", return_value=1), \
             patch("aryx.pipeline.orchestrate.resolve_run", return_value=5), \
             patch("aryx.pipeline.orchestrate.project_graph", return_value={}), \
             patch("aryx.pipeline.orchestrate.StageRunner", return_value=mock_runner), \
             patch("aryx.pipeline.orchestrate.StageTracker"), \
             patch("aryx.pipeline.orchestrate.PostgresStore"), \
             patch("aryx.pipeline.orchestrate.EntityStore"), \
             patch("aryx.pipeline.orchestrate.FalkorStore"), \
             patch("aryx.pipeline.orchestrate._build_type_ancestors", return_value={}), \
             patch("aryx.pipeline.orchestrate.ws_graph", return_value="ws_1"):
            from aryx.pipeline.orchestrate import run_pipeline
            run_pipeline(
                connector=MagicMock(), dsn="postgresql://x",
                system="sys", dataset="ds", ontology_type="T",
                match_keys=["name"], graph_url="redis://x",
                broker=MagicMock(), relate=True, max_pairs=10,
            )

        assert captured.get("max_pairs") == 10


# ---------------------------------------------------------------------------
# P7 — apply_transitive caps at transitive_max_depth
# ---------------------------------------------------------------------------

class TestTransitiveDepth:
    """P7: apply_transitive caps hops at ARYX_TRANSITIVE_MAX_DEPTH."""

    def test_transitive_cap_from_config(self, monkeypatch: pytest.MonkeyPatch):
        """With config depth=3, requesting depth=10 produces 2 hops (range(2,4))."""
        from aryx.config import get_settings
        get_settings.cache_clear()

        mock_graph = MagicMock()

        with patch("aryx.reasoning.edge_axioms.get_settings") as mock_cfg:
            mock_cfg.return_value.transitive_max_depth = 3
            from aryx.reasoning.edge_axioms import apply_transitive
            apply_transitive(mock_graph, "PART_OF", depth=10)

        # range(2, 3+1) = [2, 3] → 2 graph.run() calls
        assert mock_graph.run.call_count == 2

    def test_transitive_minimum_two_hops(self):
        """Even if depth=1 is passed, at least 2 hops are evaluated."""
        mock_graph = MagicMock()
        with patch("aryx.reasoning.edge_axioms.get_settings") as mock_cfg:
            mock_cfg.return_value.transitive_max_depth = 4
            from aryx.reasoning.edge_axioms import apply_transitive
            apply_transitive(mock_graph, "LOCATED_IN", depth=1)

        # max(2, min(1, 4)) = 2 → range(2, 3) = [2] → 1 call
        assert mock_graph.run.call_count == 1

    def test_transitive_default_four_hops(self):
        """Default config depth=4 produces 3 hops (range(2,5))."""
        mock_graph = MagicMock()
        with patch("aryx.reasoning.edge_axioms.get_settings") as mock_cfg:
            mock_cfg.return_value.transitive_max_depth = 4
            from aryx.reasoning.edge_axioms import apply_transitive
            apply_transitive(mock_graph, "REPORTS_TO", depth=4)

        # range(2, 5) = [2, 3, 4] → 3 calls
        assert mock_graph.run.call_count == 3

    def test_transitive_hop_queries_contain_edge_name(self):
        """Each Cypher query run by apply_transitive carries the edge name param."""
        mock_graph = MagicMock()
        with patch("aryx.reasoning.edge_axioms.get_settings") as mock_cfg:
            mock_cfg.return_value.transitive_max_depth = 2
            from aryx.reasoning.edge_axioms import apply_transitive
            apply_transitive(mock_graph, "SUBSIDIARY_OF", depth=2)

        for c in mock_graph.run.call_args_list:
            params = c[1].get("params") or (c[0][1] if len(c[0]) > 1 else {})
            assert params.get("name") == "SUBSIDIARY_OF"
