"""EntityStore.create_entity()'s Oracle param-count mismatch.

Regression coverage for a real bug found by post-merge review:
create_entity() always called insert_entity.sql with 4 params
(workspace_id, ontology_type, attributes, confidence), matching the
Postgres/generic query's 4 placeholders + RETURNING id. But
queries/oracle/insert_entity.sql takes an explicit id -- 5 placeholders,
no RETURNING -- so on the Oracle backend this bound the wrong number of
values and never got a row back (RuntimeError: "insert_entity returned
no row"), or a bind-count error before that.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

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


def test_create_entity_postgres_uses_4_param_returning_path():
    store, cur = _make_store()
    cur.fetchone.return_value = (42,)
    with patch("aryx.store.entity_store.get_settings") as mock_cfg, \
         patch("aryx.store.entity_store.load", side_effect=lambda name: name):
        mock_cfg.return_value.effective_db_backend.return_value = "local"
        entity_id = store.create_entity("Widget", {"a": 1}, confidence=0.9)

    assert entity_id == 42
    query_name, params = cur.execute.call_args[0]
    assert query_name == "insert_entity"
    assert len(params) == 4
    assert params[0] == 1  # workspace_id
    assert params[1] == "Widget"


def test_create_entity_oracle_fetches_id_and_uses_5_params():
    store, cur = _make_store()
    cur.fetchall.return_value = [(99,)]  # _fetch_entity_ids's id-fetch result
    with patch("aryx.store.entity_store.get_settings") as mock_cfg, \
         patch("aryx.store.entity_store.load", side_effect=lambda name: name), \
         patch("aryx.store.entity_store._fetch_entity_ids", return_value=[99]) as mock_fetch_ids:
        mock_cfg.return_value.effective_db_backend.return_value = "oci"
        entity_id = store.create_entity("Widget", {"a": 1}, confidence=0.9)

    assert entity_id == 99
    mock_fetch_ids.assert_called_once()
    # The insert call (not the id-fetch, which is mocked out) must bind 5 params.
    insert_calls = [c for c in cur.execute.call_args_list if c.args[0] == "insert_entity"]
    assert len(insert_calls) == 1
    params = insert_calls[0].args[1]
    assert len(params) == 5
    assert params[0] == 99  # explicit id
    assert params[1] == 1   # workspace_id
    assert params[2] == "Widget"
