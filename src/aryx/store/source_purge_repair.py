"""Golden-record repair step for the source-purge transaction, mixed into
SourcePurgeStore.

Split out of `store/source_purge_mutations.py` (Raven Style Compliance
Plan, Phase 2b, 2026-09-03). Zero patch risk — same reasoning as
`source_purge_mutations.py`'s docstring.
"""
from __future__ import annotations

import json
from typing import Any

from psycopg.types.json import Json

from aryx.queries import load
from aryx.store.source_purge_helpers import rebuild_survivor_states


class _SourcePurgeRepairMixin:
    """Golden-record repair for impacted entities, mixed into SourcePurgeStore."""

    def _repair_entities(
        self,
        cursor: Any,
        impacted_ids: list[int],
    ) -> tuple[list[int], int]:
        if not impacted_ids:
            return [], 0
        params = {"workspace_id": self._ws, "entity_ids": impacted_ids}
        cursor.execute(load("select_impacted_orphan_entity_ids"), params)
        orphan_ids = sorted(int(row[0]) for row in cursor.fetchall())

        cursor.execute(load("select_impacted_survivor_members"), params)
        member_rows = cursor.fetchall()
        cursor.execute(load("select_workspace_survivorship"), (self._ws,))
        policy_row = cursor.fetchone()
        policy_data = policy_row[0] if policy_row else {}
        if isinstance(policy_data, str):
            policy_data = json.loads(policy_data)
        states = rebuild_survivor_states(member_rows, policy_data)

        update_rows = [
            (
                Json(state.attributes),
                state.confidence,
                entity_id,
                self._ws,
            )
            for entity_id, state in sorted(states.items())
        ]
        if update_rows:
            cursor.executemany(load("repair_entity_after_source_purge"), update_rows)

        conflict_rows = [
            (
                self._ws,
                entity_id,
                conflict["attribute"],
                Json(conflict["winning_value"]),
                Json(conflict["losing_values"]),
                conflict["strategy"],
            )
            for entity_id, state in sorted(states.items())
            for conflict in state.conflicts
        ]
        if conflict_rows:
            cursor.executemany(load("insert_attribute_conflict"), conflict_rows)

        if orphan_ids:
            cursor.execute(load("delete_impacted_entities"), {
                "workspace_id": self._ws,
                "entity_ids": orphan_ids,
            })
        return orphan_ids, len(states)
