"""Regression coverage for ProjectionStore (G8 incremental projection).

docs/ingestion/SPARK_PARALLEL_MIGRATION_ANALYSIS_2026-09-23.md Phase 4:
wiring project_auto() into the confirm pipeline surfaced a real, live-only
bug in advance_watermark() -- oracledb's thin-mode driver requires one
positional bind value per *occurrence* of a numbered placeholder (:1) in
the SQL text when params are passed as a tuple, not one per distinct
placeholder name. upsert_projection_state.sql's Oracle override references
:1 twice (the MERGE...USING DUAL ON clause and the INSERT VALUES), so a
1-element tuple raised DPY-4009 -- confirmed live against a real Oracle
ADB, invisible to any mock-based test since it depends on the real
driver's bind-counting behavior. Fixed by switching to a named bind
(:workspace_id) passed as a dict, which oracledb correctly dedupes
regardless of occurrence count.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.store.projection_store import ProjectionStore


def _store_with_cursor(cursor: MagicMock) -> ProjectionStore:
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    pool = MagicMock()
    pool.connection.return_value = conn
    with patch("aryx.store.projection_store.get_pool", return_value=pool):
        return ProjectionStore("postgresql://test", workspace_id=7)


def test_advance_watermark_passes_a_dict_not_a_positional_tuple() -> None:
    """Regression guard for the DPY-4009 bug above: a dict lets oracledb
    dedupe a bind name referenced more than once in the SQL text; a
    positional tuple does not."""
    cursor = MagicMock()
    store = _store_with_cursor(cursor)

    store.advance_watermark()

    (_sql, params), _kwargs = cursor.execute.call_args
    assert params == {"workspace_id": 7}
    assert not isinstance(params, tuple)


def test_dirty_relationship_entity_ids_passes_workspace_and_since_twice() -> None:
    """select_dirty_relationship_entity_ids.sql UNIONs two SELECTs, each
    filtering by workspace_id and since -- the call must supply both
    positionally, in SQL order, for the plain %s -> :1.. translation to
    line up correctly on Oracle."""
    cursor = MagicMock()
    cursor.fetchall.return_value = [(101,), (102,)]
    store = _store_with_cursor(cursor)

    result = store.dirty_relationship_entity_ids("2026-09-23T00:00:00Z")

    assert result == [101, 102]
    (_sql, params), _kwargs = cursor.execute.call_args
    assert params == (7, "2026-09-23T00:00:00Z", 7, "2026-09-23T00:00:00Z")


def test_watermark_returns_none_when_no_row() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    store = _store_with_cursor(cursor)

    assert store.watermark() is None
