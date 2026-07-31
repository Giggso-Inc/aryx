"""Regression coverage for source-scoped entity repair."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aryx.store.source_purge_store import (
    SourcePurgeBusy,
    SourcePurgeStore,
    rebuild_survivor_states,
)


ROOT = Path(__file__).resolve().parents[1]


def test_rebuild_survivor_states_uses_only_remaining_members() -> None:
    rows = [
        (
            42,
            2,
            {"name": "Alice", "email": "new@example.com"},
            "crm",
            datetime(2026, 7, 2, tzinfo=timezone.utc),
        ),
        (
            42,
            3,
            {"name": "Alice", "email": "old@example.com"},
            "billing",
            datetime(2026, 7, 1, tzinfo=timezone.utc),
        ),
    ]

    states = rebuild_survivor_states(
        rows,
        {
            "default_strategy": "most_recent",
        },
    )

    assert states[42].attributes == {
        "name": "Alice",
        "email": "new@example.com",
    }
    assert states[42].confidence == 0.5
    assert states[42].conflicts == [
        {
            "attribute": "email",
            "winning_value": "new@example.com",
            "losing_values": [
                {
                    "value": "old@example.com",
                    "source_system": "billing",
                    "record_id": 3,
                },
            ],
            "strategy": "most_recent",
        },
    ]


def test_rebuild_survivor_states_does_not_create_unrelated_entities() -> None:
    states = rebuild_survivor_states(
        [
            (
                7,
                11,
                {"name": "Remaining"},
                "crm",
                datetime(2026, 7, 1, tzinfo=timezone.utc),
            ),
        ],
        {},
    )

    assert set(states) == {7}


class _FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.executemany_calls: list[tuple[str, object]] = []
        self.rowcount = 0
        self._last_sql = ""
        self.rowcounts = {
            "DELETE FROM aryx_relationship": 3,
            "DELETE FROM aryx_projected_entity": 2,
            "DELETE FROM aryx_attribute_conflict": 1,
            "DELETE FROM aryx_axiom_violation": 4,
            "DELETE FROM aryx_entity_member": 2,
            "DELETE FROM aryx_landed_record": 2,
            "DELETE FROM aryx_run_stage": 5,
            "DELETE FROM aryx_match_edge": 6,
            "DELETE FROM aryx_run": 1,
            "DELETE FROM aryx_datasource": 1,
        }

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> None:
        self.calls.append((sql, params))
        self._last_sql = sql
        self.rowcount = next(
            (count for prefix, count in self.rowcounts.items() if sql.startswith(prefix)),
            0,
        )

    def executemany(self, sql: str, rows: object) -> None:
        self.executemany_calls.append((sql, rows))
        self.rowcount = len(rows) if hasattr(rows, "__len__") else 0

    def fetchone(self) -> tuple | None:
        if self._last_sql.startswith("SELECT id\nFROM aryx_workspace"):
            return (1,)
        if self._last_sql.startswith("SELECT job_id, status\nFROM aryx_job"):
            return None
        if self._last_sql.startswith("SELECT survivorship FROM aryx_workspace"):
            return ({"default_strategy": "most_recent"},)
        if self._last_sql.startswith("UPDATE aryx_datasource"):
            return (9,)
        return None

    def fetchall(self) -> list[tuple]:
        if self._last_sql.startswith("SELECT DISTINCT m.entity_id"):
            return [(101,), (202,)]
        if self._last_sql.startswith("SELECT e.id\nFROM aryx_entity e"):
            return [(202,)]
        if self._last_sql.startswith("SELECT m.entity_id"):
            return [
                (
                    101,
                    12,
                    {"name": "Alice", "email": "new@example.com"},
                    "crm",
                    datetime(2026, 7, 2, tzinfo=timezone.utc),
                ),
                (
                    101,
                    13,
                    {"name": "Alice", "email": "old@example.com"},
                    "billing",
                    datetime(2026, 7, 1, tzinfo=timezone.utc),
                ),
            ]
        return []


class _MissingWorkspaceCursor(_FakeCursor):
    def fetchone(self) -> tuple | None:
        if self._last_sql.startswith("SELECT id\nFROM aryx_workspace"):
            return None
        return super().fetchone()


class _BusyCursor(_FakeCursor):
    def fetchone(self) -> tuple | None:
        if self._last_sql.startswith("SELECT job_id, status\nFROM aryx_job"):
            return ("job-1", "running")
        return super().fetchone()


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def cursor(self) -> _FakeCursor:
        return self._cursor


def _store_with_cursor(cursor: _FakeCursor) -> SourcePurgeStore:
    pool = MagicMock()
    pool.connection.return_value = _FakeConnection(cursor)
    with patch("aryx.store.source_purge_store.get_pool", return_value=pool):
        return SourcePurgeStore("postgresql://test", workspace_id=1)


def test_purge_transaction_rebuilds_survivors_and_counts_run_delete() -> None:
    cursor = _FakeCursor()
    store = _store_with_cursor(cursor)

    stats = store.purge(
        [("csv", "orders"), ("csv", "orders")],
        catalog_delete_ids=[9],
    )

    assert stats["sources_purged"] == 1
    assert stats["landed_records_deleted"] == 2
    assert stats["members_deleted"] == 2
    assert stats["entities_impacted"] == 2
    assert stats["entities_deleted"] == 1
    assert stats["survivors_rebuilt"] == 1
    assert stats["runs_deleted"] == 1
    assert stats["catalog_rows_deleted"] == 1
    assert stats["relationships_invalidated"] == 3
    assert stats["projected_entities_invalidated"] == 2
    assert stats["conflicts_replaced"] == 1
    assert stats["violations_invalidated"] == 4
    assert stats["entity_ids_deleted"] == [202]
    assert cursor.executemany_calls[0][0].startswith("UPDATE aryx_entity")
    assert cursor.executemany_calls[1][0].startswith("INSERT INTO aryx_attribute_conflict")


def test_purge_missing_workspace_raises_value_error() -> None:
    store = _store_with_cursor(_MissingWorkspaceCursor())

    with pytest.raises(ValueError, match="workspace 1 not found"):
        store.purge([("csv", "orders")])


def test_purge_active_workspace_job_raises_busy() -> None:
    store = _store_with_cursor(_BusyCursor())

    with pytest.raises(SourcePurgeBusy, match="job-1"):
        store.purge([("csv", "orders")])


def test_oracle_impacted_queries_use_json_table_for_large_id_sets() -> None:
    query_dir = ROOT / "src" / "aryx" / "queries" / "oracle"
    query_names = (
        "delete_impacted_entities.sql",
        "delete_impacted_relationships.sql",
        "select_impacted_orphan_entity_ids.sql",
        "select_impacted_survivor_members.sql",
    )

    for query_name in query_names:
        sql = (query_dir / query_name).read_text(encoding="utf-8")
        assert "JSON_TABLE" in sql
        assert "workspace_id" in sql


def test_oracle_source_purge_queries_have_explicit_overrides() -> None:
    query_dir = ROOT / "src" / "aryx" / "queries" / "oracle"
    query_names = (
        "delete_source_entity_members.sql",
        "delete_source_landed_records.sql",
        "invalidate_projection_state.sql",
        "lock_workspace_for_mutation.sql",
        "select_active_workspace_job.sql",
        "select_source_impacted_entity_ids.sql",
        "purge_source_run_data.sql",
    )

    for query_name in query_names:
        sql = (query_dir / query_name).read_text(encoding="utf-8")
        assert sql.strip()
