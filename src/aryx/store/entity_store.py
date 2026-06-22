"""Persistence + record loading for entity resolution (stage 7).

Reads a run's landed records (building match text from key attributes) and
writes resolved entities plus their provenance members. SQL lives in queries/.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from typing import Any

from psycopg.types.json import Json

from aryx.models import (
    EntityMember,
    Relationship,
    ResolutionRecord,
    ResolvedEntity,
)
from aryx.config import get_settings
from aryx.queries import load
from aryx.store.pool import get_pool

logger = logging.getLogger(__name__)


def _dumps(value: object) -> str:
    """JSON-encode, stringifying non-native types."""
    return json.dumps(value, default=str)


class EntityStore:
    """Loads landed records and persists resolved entities + members."""

    def __init__(self, dsn: str, workspace_id: int = 1) -> None:
        """Acquire the shared connection pool for this DSN."""
        self._pool = get_pool(dsn)
        self._ws = workspace_id

    def landed_records(self, run_id: int, key_attrs: list[str]) -> list[ResolutionRecord]:
        """Read a run's landed records, building match text from key attributes.

        Args:
            run_id: The discovery run to load.
            key_attrs: Payload keys whose values form the match text.

        Returns:
            One ResolutionRecord per landed row.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_landed_by_run"), (run_id, self._ws))
                rows = cur.fetchall()
        records = []
        for record_id, payload, source_system, cleaned_at in rows:
            text = " ".join(str(payload.get(a, "")) for a in key_attrs).strip()
            records.append(ResolutionRecord(
                record_id=record_id, text=text, payload=payload,
                source_system=source_system, cleaned_at=cleaned_at,
            ))
        return records

    def save(self, results: list[tuple[ResolvedEntity, list[EntityMember]]]) -> int:
        """Persist resolved entities and their provenance members.

        Returns the number of entities written.
        """
        count = 0
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                for entity, members in results:
                    cur.execute(
                        load("insert_entity"),
                        (self._ws, entity.ontology_type,
                         Json(entity.attributes, dumps=_dumps), entity.confidence),
                    )
                    row = cur.fetchone()
                    entity_id = int(row[0]) if row else 0
                    for member in members:
                        cur.execute(
                            load("insert_entity_member"),
                            (self._ws, entity_id, member.landed_record_id,
                             member.confidence),
                        )
                    for conflict in entity.conflicts or []:
                        cur.execute(
                            load("insert_attribute_conflict"),
                            (self._ws, entity_id, conflict["attribute"],
                             Json(conflict["winning_value"], dumps=_dumps),
                             Json(conflict["losing_values"], dumps=_dumps),
                             conflict["strategy"]),
                        )
                    count += 1
        logger.info("entities saved count=%d", count)
        return count

    def save_relationships(self, relationships: list[Relationship]) -> None:
        """Persist inferred relationships between entities (stage 8)."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    load("insert_relationship"),
                    [(self._ws, r.source_entity_id, r.target_entity_id,
                      r.name, r.confidence) for r in relationships],
                )

    def list_entities(self) -> Iterator[tuple[int, str, dict]]:
        """Yield (id, ontology_type, attributes) for graph projection.

        Server-side named cursor + generator: only one batch is held in Python
        memory at a time. Callers that need full-list semantics (len, indexing,
        multiple passes) must materialise explicitly: list(store.list_entities()).
        """
        batch_size = get_settings().batch_size
        with self._pool.connection() as conn:
            with conn.cursor(f"list_entities_cur_{self._ws}_{uuid.uuid4().hex[:8]}") as cur:
                cur.execute(load("select_entities"), (self._ws,))
                while batch := cur.fetchmany(batch_size):
                    yield from ((r[0], r[1], r[2]) for r in batch)

    def list_members_provenance(self) -> Iterator[tuple[int, str, str, str]]:
        """Yield (entity_id, system, dataset, record_id) provenance edges.

        See list_entities() for the streaming / materialise contract.
        """
        batch_size = get_settings().batch_size
        with self._pool.connection() as conn:
            with conn.cursor(f"list_provenance_cur_{self._ws}_{uuid.uuid4().hex[:8]}") as cur:
                cur.execute(load("select_members_provenance"), (self._ws,))
                while batch := cur.fetchmany(batch_size):
                    yield from ((r[0], r[1], r[2], r[3]) for r in batch)

    def list_relationships(self) -> Iterator[tuple[int, int, str]]:
        """Yield (source_entity_id, target_entity_id, name) edges.

        See list_entities() for the streaming / materialise contract.
        """
        batch_size = get_settings().batch_size
        with self._pool.connection() as conn:
            with conn.cursor(f"list_relationships_cur_{self._ws}_{uuid.uuid4().hex[:8]}") as cur:
                cur.execute(load("select_relationships"), (self._ws,))
                while batch := cur.fetchmany(batch_size):
                    yield from ((r[0], r[1], r[2]) for r in batch)

    def match_entities(self, when: dict) -> Iterator[dict[str, Any]]:
        """Yield entities matching a rule when-clause, pushes type+attr into SQL.

        Filters by ontology_type equality and attribute-key existence in the
        database so only candidate rows reach Python. The op/value comparison
        runs in the caller (_match) to preserve edge-case handling (TypeError,
        None values). Yields dicts with keys: id, type, attributes.

        See list_entities() for the streaming / materialise contract.
        """
        entity_type = when.get("type") or None
        attr = when.get("attr") or None
        batch_size = get_settings().batch_size
        with self._pool.connection() as conn:
            with conn.cursor(f"match_entities_cur_{self._ws}_{uuid.uuid4().hex[:8]}") as cur:
                cur.execute(
                    load("select_entities_matching"),
                    (self._ws, entity_type, entity_type, attr, attr),
                )
                while batch := cur.fetchmany(batch_size):
                    yield from (
                        {"id": r[0], "type": r[1], "attributes": r[2]}
                        for r in batch
                    )

    def clear_relationships(self) -> int:
        """Delete all relationships for this workspace; return rows removed.

        Makes re-deriving FK edges idempotent (link_by_attribute appends).
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("delete_relationships"), (self._ws,))
                return cur.rowcount

    def close(self) -> None:
        """No-op: connections are managed by the shared pool (G12)."""
