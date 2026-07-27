"""Tests for two FalkorDB/ontology-export reliability fixes.

1. GraphReader._query() passes a configurable per-query timeout to FalkorDB
   instead of relying on its built-in 5000ms default. Real incident: GET
   /graph on workspace 44/45 returned 500
   (redis.exceptions.ResponseError: Query timed out) — some
   relationship-traversal queries on large, heavily-linked workspaces
   legitimately take longer than 5s even with REL.name indexed. Fix:
   ARYX_GRAPH_QUERY_TIMEOUT (default 30000ms), 0 disables the override
   (falls back to FalkorDB's own default).

2. GET /ontology/export caps synchronous export at
   ARYX_ONTOLOGY_EXPORT_MAX_ENTITIES entities (default 50,000), returning a
   clean 413 instead of risking the reverse proxy killing the connection
   (502 Bad Gateway) partway through serialising a huge workspace.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Real Settings object — no mocking. Guards against the exact class of bug
# where every other test here patches get_settings() with a bare MagicMock,
# which fabricates any attribute access rather than raising AttributeError —
# so a field referenced by call sites but never actually added to Settings
# passed every mocked test while crashing in real production.
# ---------------------------------------------------------------------------

class TestRealSettingsHaveTheseFields:
    def test_graph_query_timeout_exists_on_real_settings(self):
        from aryx.config import get_settings
        get_settings.cache_clear()
        settings = get_settings()
        assert isinstance(settings.graph_query_timeout, int)
        assert settings.graph_query_timeout == 30_000
        get_settings.cache_clear()

    def test_ontology_export_max_entities_exists_on_real_settings(self):
        from aryx.config import get_settings
        get_settings.cache_clear()
        settings = get_settings()
        assert isinstance(settings.ontology_export_max_entities, int)
        assert settings.ontology_export_max_entities == 50_000
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# GraphReader._query() timeout
# ---------------------------------------------------------------------------

def _mock_query_result(rows):
    result = MagicMock()
    result.result_set = rows
    return result


class TestGraphQueryTimeout:
    def test_query_passes_configured_timeout_to_falkordb(self):
        from aryx.graph.reader import GraphReader

        mock_graph = MagicMock()
        mock_graph.query.return_value = _mock_query_result([])

        with patch("aryx.graph.reader.FalkorDB") as MockDB, \
             patch("aryx.graph.reader.get_settings") as mock_cfg:
            mock_cfg.return_value.graph_query_timeout = 30_000
            MockDB.return_value.select_graph.return_value = mock_graph
            reader = GraphReader("redis://localhost:6379")
            reader._query("MATCH (e:Entity) RETURN e.id")

        _, kwargs = mock_graph.query.call_args
        assert kwargs["timeout"] == 30_000

    def test_zero_timeout_setting_disables_the_override(self):
        """0 means 'use FalkorDB's own built-in default', passed as None —
        not a literal 0ms timeout, which would fail every query instantly."""
        from aryx.graph.reader import GraphReader

        mock_graph = MagicMock()
        mock_graph.query.return_value = _mock_query_result([])

        with patch("aryx.graph.reader.FalkorDB") as MockDB, \
             patch("aryx.graph.reader.get_settings") as mock_cfg:
            mock_cfg.return_value.graph_query_timeout = 0
            MockDB.return_value.select_graph.return_value = mock_graph
            reader = GraphReader("redis://localhost:6379")
            reader._query("MATCH (e:Entity) RETURN e.id")

        _, kwargs = mock_graph.query.call_args
        assert kwargs["timeout"] is None

    def test_timeout_is_configurable_not_hardcoded(self):
        """A different configured value must reach FalkorDB unchanged —
        proves this reads live config, not a baked-in constant."""
        from aryx.graph.reader import GraphReader

        mock_graph = MagicMock()
        mock_graph.query.return_value = _mock_query_result([])

        with patch("aryx.graph.reader.FalkorDB") as MockDB, \
             patch("aryx.graph.reader.get_settings") as mock_cfg:
            mock_cfg.return_value.graph_query_timeout = 120_000
            MockDB.return_value.select_graph.return_value = mock_graph
            reader = GraphReader("redis://localhost:6379")
            reader._query("MATCH (e:Entity) RETURN e.id")

        _, kwargs = mock_graph.query.call_args
        assert kwargs["timeout"] == 120_000


# ---------------------------------------------------------------------------
# GET /ontology/export entity-count cap
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    from aryx.api.ontology_api import ontology_router
    app = FastAPI()
    app.include_router(ontology_router())
    return TestClient(app, raise_server_exceptions=False)


def _patch_export_enabled():
    return patch.multiple(
        "aryx.api.ontology_api.export_runtime",
        is_enabled=MagicMock(return_value=True),
        enabled_formats=MagicMock(return_value=["turtle"]),
        status=MagicMock(return_value={
            "include_provenance": False, "base_uri": "https://aryx.local/",
        }),
    )


class TestOntologyExportCap:
    def test_export_over_cap_returns_413_without_loading_bundle(self, client):
        """Over the cap: reject with 413 before ever calling _load_bundle —
        the whole point is to avoid starting the expensive synchronous work
        that would otherwise risk a reverse-proxy 502 partway through."""
        mock_estore = MagicMock()
        mock_estore.count_entities.return_value = 75_000
        with _patch_export_enabled(), \
             patch("aryx.api.ontology_api.get_settings") as mock_cfg, \
             patch("aryx.api.ontology_api.EntityStore", return_value=mock_estore), \
             patch("aryx.api.ontology_api._load_bundle") as mock_load:
            mock_cfg.return_value.ontology_export_max_entities = 50_000
            resp = client.get("/ontology/export", params={"workspace_id": 45})

        assert resp.status_code == 413
        assert "75,000" in resp.text
        assert "50,000" in resp.text
        mock_load.assert_not_called()
        mock_estore.close.assert_called_once()

    def test_export_under_cap_proceeds_normally(self, client):
        mock_estore = MagicMock()
        mock_estore.count_entities.return_value = 100
        with _patch_export_enabled(), \
             patch("aryx.api.ontology_api.get_settings") as mock_cfg, \
             patch("aryx.api.ontology_api.EntityStore", return_value=mock_estore), \
             patch("aryx.api.ontology_api._load_bundle", return_value=MagicMock()), \
             patch("aryx.api.ontology_api.serialize",
                   return_value=(b"@prefix : <x> .", "text/turtle", "ttl")):
            mock_cfg.return_value.ontology_export_max_entities = 50_000
            resp = client.get("/ontology/export", params={"workspace_id": 45})

        assert resp.status_code == 200
        assert resp.content == b"@prefix : <x> ."

    def test_cap_disabled_when_zero_skips_the_count_query_entirely(self, client):
        """0 disables the cap — must not even query the entity count, so a
        workspace's export is never blocked by this feature when it's off."""
        mock_estore = MagicMock()
        with _patch_export_enabled(), \
             patch("aryx.api.ontology_api.get_settings") as mock_cfg, \
             patch("aryx.api.ontology_api.EntityStore", return_value=mock_estore), \
             patch("aryx.api.ontology_api._load_bundle", return_value=MagicMock()), \
             patch("aryx.api.ontology_api.serialize",
                   return_value=(b"data", "text/turtle", "ttl")):
            mock_cfg.return_value.ontology_export_max_entities = 0
            resp = client.get("/ontology/export", params={"workspace_id": 45})

        assert resp.status_code == 200
        mock_estore.count_entities.assert_not_called()

    def test_exactly_at_cap_is_allowed(self, client):
        """The cap is exclusive (> cap rejected), so a workspace with
        exactly the cap's entity count must still export successfully."""
        mock_estore = MagicMock()
        mock_estore.count_entities.return_value = 50_000
        with _patch_export_enabled(), \
             patch("aryx.api.ontology_api.get_settings") as mock_cfg, \
             patch("aryx.api.ontology_api.EntityStore", return_value=mock_estore), \
             patch("aryx.api.ontology_api._load_bundle", return_value=MagicMock()), \
             patch("aryx.api.ontology_api.serialize",
                   return_value=(b"data", "text/turtle", "ttl")):
            mock_cfg.return_value.ontology_export_max_entities = 50_000
            resp = client.get("/ontology/export", params={"workspace_id": 45})

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# EntityStore.count_entities()
# ---------------------------------------------------------------------------

class TestEntityStoreCountEntities:
    def test_count_entities_scopes_to_workspace(self):
        from aryx.store.entity_store import EntityStore

        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (42,)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_pool = MagicMock()
        mock_pool.connection.return_value.__enter__.return_value = mock_conn

        with patch("aryx.store.entity_store.get_pool", return_value=mock_pool):
            store = EntityStore("postgresql://test", workspace_id=45)
            count = store.count_entities()

        assert count == 42
        sql, params = mock_cur.execute.call_args[0]
        assert "workspace_id" in sql
        assert params == (45,)
