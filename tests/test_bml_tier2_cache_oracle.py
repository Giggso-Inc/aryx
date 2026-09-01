"""BmlEvaluator._durable_put()'s Oracle branch.

Oracle has no ON CONFLICT ... DO UPDATE -- the translated
upsert_bml_tier2_cache.sql only strips ON CONFLICT and swallows the
resulting ORA-00001, which correctly emulates a fresh insert but would
silently no-op instead of refreshing an existing row's result. _durable_put
checks for the existing row first and issues an explicit UPDATE when found.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.cpq.bml import BmlEvaluator


def _make_pool_cursor(exists: bool):
    cur = MagicMock()
    cur.fetchone.return_value = (1,) if exists else None
    cur_cm = MagicMock()
    cur_cm.__enter__ = MagicMock(return_value=cur)
    cur_cm.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cur_cm)
    conn_cm = MagicMock()
    conn_cm.__enter__ = MagicMock(return_value=conn)
    conn_cm.__exit__ = MagicMock(return_value=False)
    pool = MagicMock()
    pool.connection = MagicMock(return_value=conn_cm)
    return pool, cur


def _evaluator() -> BmlEvaluator:
    ev = BmlEvaluator.__new__(BmlEvaluator)
    ev._workspace_id = 1
    return ev


def test_durable_put_updates_existing_row_on_oracle():
    pool, cur = _make_pool_cursor(exists=True)
    with patch("aryx.store.pool.get_pool", return_value=pool), \
         patch("aryx.config.get_settings") as mock_cfg:
        mock_cfg.return_value.effective_dsn.return_value = "tcps://test"
        mock_cfg.return_value.effective_db_backend.return_value = "oci"
        _evaluator()._durable_put("key1", "hide", {"v": 1})

    calls = [c.args[0] for c in cur.execute.call_args_list]
    assert any("select_bml_tier2_cache_exists" not in str(c) for c in calls)
    # Second call must be the UPDATE path, not the INSERT/upsert path.
    assert cur.execute.call_count == 2


def test_durable_put_inserts_new_row_on_oracle():
    pool, cur = _make_pool_cursor(exists=False)
    with patch("aryx.store.pool.get_pool", return_value=pool), \
         patch("aryx.config.get_settings") as mock_cfg:
        mock_cfg.return_value.effective_dsn.return_value = "tcps://test"
        mock_cfg.return_value.effective_db_backend.return_value = "oci"
        _evaluator()._durable_put("key2", "hide", {"v": 2})

    assert cur.execute.call_count == 2


def test_durable_put_single_call_on_postgres():
    pool, cur = _make_pool_cursor(exists=False)
    with patch("aryx.store.pool.get_pool", return_value=pool), \
         patch("aryx.config.get_settings") as mock_cfg:
        mock_cfg.return_value.effective_dsn.return_value = "postgresql://test"
        mock_cfg.return_value.effective_db_backend.return_value = "local"
        _evaluator()._durable_put("key3", "hide", {"v": 3})

    # No existence pre-check on Postgres -- ON CONFLICT DO UPDATE handles it
    # in one round-trip.
    assert cur.execute.call_count == 1
