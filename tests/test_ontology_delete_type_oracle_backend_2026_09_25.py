"""DELETE /ontology/types/{name} 500'd unconditionally on the Oracle backend.

Regression coverage for two distinct bugs found via real-data testing
against workspace 704 on the dev_oci deployment
(CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T9/T11 follow-up):

1. EntityStore.delete_entities_by_type() always ran a plain
   ``DELETE ... RETURNING id`` and called cur.fetchall() to read the
   deleted ids back -- works on psycopg (Postgres) but python-oracledb
   raises DPY-1003 ("the executed statement does not return rows") for a
   DELETE with no proper RETURNING ... INTO bind setup. Oracle now
   selects the ids first, then deletes by the same predicate.

2. ontology_api.py::delete_type()'s graph cascade step always
   instantiated FalkorStore regardless of ARYX_GRAPH_BACKEND -- the same
   "assumes FalkorDB everywhere" pattern already fixed once for
   admin_api.py::rebuild_graph(). On an ARYX_GRAPH_BACKEND=oci_graph
   deployment there is no FalkorDB to connect to, so this failed even
   after bug 1 above was fixed.

Both fixes were validated live: creating a scratch entity, deleting its
type via the real HTTP endpoint, and confirming the row was gone.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aryx.api.ontology.ontology_api import ontology_router
from aryx.store.entity_store import EntityStore


def _make_store():
    store = EntityStore.__new__(EntityStore)
    store._ws = 1
    store._pool = MagicMock()
    cur = MagicMock()
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    store._pool.connection.return_value = conn
    return store, cur


def test_delete_entities_by_type_postgres_uses_returning_fetchall():
    store, cur = _make_store()
    cur.fetchall.return_value = [(1,), (2,)]
    with patch("aryx.store.entity_store.get_settings") as mock_cfg, \
         patch("aryx.store.entity_store.load", side_effect=lambda name: name):
        mock_cfg.return_value.effective_db_backend.return_value = "local"
        ids = store.delete_entities_by_type("Widget")

    assert ids == [1, 2]
    assert cur.execute.call_count == 1
    query_name, params = cur.execute.call_args[0]
    assert query_name == "delete_entities_by_type"
    assert params == (1, "Widget")


def test_delete_entities_by_type_oracle_selects_ids_then_deletes():
    store, cur = _make_store()
    cur.fetchall.return_value = [(1,), (2,)]  # only used by the select
    with patch("aryx.store.entity_store.get_settings") as mock_cfg, \
         patch("aryx.store.entity_store.load", side_effect=lambda name: name):
        mock_cfg.return_value.effective_db_backend.return_value = "oci"
        ids = store.delete_entities_by_type("Widget")

    assert ids == [1, 2]
    assert cur.execute.call_count == 2
    select_call, delete_call = cur.execute.call_args_list
    assert select_call.args[0] == "select_entity_ids_by_type"
    assert select_call.args[1] == (1, "Widget")
    assert delete_call.args[0] == "delete_entities_by_type"
    assert delete_call.args[1] == (1, "Widget")
    # DELETE must not read a return value on this backend (DPY-1003 guard).
    cur.fetchall.assert_called_once()


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(ontology_router())
    return TestClient(app, raise_server_exceptions=False)


def _patched_entity_store(deleted_ids):
    mock_estore = MagicMock()
    mock_estore.delete_entities_by_type.return_value = deleted_ids
    return mock_estore


def test_delete_type_falkordb_backend_uses_falkorstore(client):
    """Default/explicit non-oci_graph backend still takes the FalkorStore path."""
    mock_estore = _patched_entity_store([1, 2, 3])
    mock_ob_result = {"status": "deleted", "name": "Widget"}
    with (
        patch("aryx.api.security._verify_key", return_value=True),
        patch("aryx.api.ontology.ontology_api.get_settings") as mock_cfg,
        patch("aryx.api.ontology.ontology_api.EntityStore", return_value=mock_estore),
        patch("aryx.api.ontology.ontology_api.FalkorStore") as mock_falkor,
        patch("aryx.api.ontology.ontology_api._ob.delete_type", return_value=mock_ob_result),
    ):
        mock_cfg.return_value.effective_graph_backend.return_value = "falkordb"
        resp = client.delete(
            "/ontology/types/Widget?workspace_id=1",
            headers={"x-aryx-api-key": "valid-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["entities_deleted"] == 3
    mock_falkor.assert_called_once()
    mock_falkor.return_value.remove_entities_by_type.assert_called_once_with("Widget")


def test_delete_type_oci_graph_backend_uses_oracle_graph_store(client):
    """ARYX_GRAPH_BACKEND=oci_graph must cascade into OracleGraphStore, not
    silently try to reach a FalkorDB that doesn't exist on this deployment."""
    mock_estore = _patched_entity_store([1])
    mock_oracle_store = MagicMock()
    mock_ob_result = {"status": "deleted", "name": "Widget"}
    with (
        patch("aryx.api.security._verify_key", return_value=True),
        patch("aryx.api.ontology.ontology_api.get_settings") as mock_cfg,
        patch("aryx.api.ontology.ontology_api.EntityStore", return_value=mock_estore),
        patch("aryx.api.ontology.ontology_api.FalkorStore") as mock_falkor,
        patch(
            "aryx.graph.oracle_graph_store.OracleGraphStore",
            return_value=mock_oracle_store,
        ) as mock_oracle_cls,
        patch("aryx.api.ontology.ontology_api._ob.delete_type", return_value=mock_ob_result),
    ):
        mock_cfg.return_value.oci_adb_dsn = "tcps://test:1522/db"
        mock_cfg.return_value.effective_graph_backend.return_value = "oci_graph"
        resp = client.delete(
            "/ontology/types/Widget?workspace_id=704",
            headers={"x-aryx-api-key": "valid-key"},
        )

    assert resp.status_code == 200
    mock_oracle_cls.assert_called_once_with("tcps://test:1522/db", 704)
    mock_falkor.assert_not_called()
    mock_oracle_store.remove_entities_by_type.assert_called_once_with("Widget")


def test_delete_type_oci_graph_backend_missing_dep_returns_503(client):
    """Missing OCI extras must fail loudly (503), not silently fall back to
    rebuilding/deleting against the wrong graph backend."""
    mock_estore = _patched_entity_store([])
    with (
        patch("aryx.api.security._verify_key", return_value=True),
        patch("aryx.api.ontology.ontology_api.get_settings") as mock_cfg,
        patch("aryx.api.ontology.ontology_api.EntityStore", return_value=mock_estore),
        patch("aryx.api.ontology.ontology_api.FalkorStore") as mock_falkor,
    ):
        mock_cfg.return_value.oci_adb_dsn = "tcps://test:1522/db"
        mock_cfg.return_value.effective_graph_backend.return_value = "oci_graph"
        import sys
        with patch.dict(sys.modules, {"aryx.graph.oracle_graph_store": None}):
            resp = client.delete(
                "/ontology/types/Widget?workspace_id=704",
                headers={"x-aryx-api-key": "valid-key"},
            )

    assert resp.status_code == 503
    mock_falkor.assert_not_called()


def test_oracle_graph_store_remove_entities_by_type_deletes_in_order():
    """remove_entities_by_type() must clear provenance and edges before
    vertices, mirroring the FK-safe order used by clear() and remove_entity()."""
    from aryx.graph.oracle_graph_store import OracleGraphStore

    store = OracleGraphStore.__new__(OracleGraphStore)
    store._workspace_id = 704
    store._pool = MagicMock()
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    store._pool.connection.return_value = conn

    with patch("aryx.graph.oracle_graph_store.load", side_effect=lambda name: name):
        store.remove_entities_by_type("Widget")

    calls = [c.args[0] for c in conn.execute.call_args_list]
    assert calls == [
        "delete_graph_provenance_by_type",
        "delete_graph_edge_by_type",
        "delete_graph_vertex_by_type",
    ]
    for c in conn.execute.call_args_list:
        assert c.args[1] == {"ws": 704, "typ": "Widget"}
