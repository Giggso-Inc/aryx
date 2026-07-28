"""Regression coverage for source-scoped entity repair."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from aryx.store.source_purge_store import rebuild_survivor_states


ROOT = Path(__file__).resolve().parents[1]


def test_rebuild_survivor_states_uses_only_remaining_members() -> None:
    rows = [
        (
            42,
            2,
            {"name": "Alice", "email": "new@example.com"},
            "crm",
            datetime(2026, 7, 2, tzinfo=UTC),
        ),
        (
            42,
            3,
            {"name": "Alice", "email": "old@example.com"},
            "billing",
            datetime(2026, 7, 1, tzinfo=UTC),
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
                datetime(2026, 7, 1, tzinfo=UTC),
            ),
        ],
        {},
    )

    assert set(states) == {7}


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
