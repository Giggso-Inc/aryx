"""Postgres ChunkBackend for chunked resolution (G1).

Block membership, done markers, and match edges live in Postgres so a
crashed resolution resumes from the first unscored block. Uses the shared
connection pool; SQL lives in queries/ per house rule.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator

from aryx.models import ResolutionRecord
from aryx.queries import load
from aryx.store.pool import get_pool

logger = logging.getLogger(__name__)


class PgChunkBackend:
    """ChunkBackend over aryx_block_member / aryx_block_done / aryx_match_edge."""

    def __init__(self, dsn: str, workspace_id: int = 1,
                 key_attrs: list[str] | None = None) -> None:
        """Bind to a workspace; key_attrs build match text on record load."""
        self._pool = get_pool(dsn)
        self._ws = workspace_id
        self._key_attrs = key_attrs or []

    def has_keys(self, run_id: int) -> bool:
        """True when the key pass already ran for this run (resume)."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("count_block_members"), (run_id,))
                row = cur.fetchone()
        return bool(row and row[0])

    def add_members(self, run_id: int, rows: list[tuple[str, int]]) -> None:
        """Bulk-insert (block_key, record_id) membership rows."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(load("insert_block_member"),
                                [(run_id, key, rid) for key, rid in rows])

    def todo_blocks(self, run_id: int) -> Iterator[str]:
        """Distinct block keys without a done marker, stable order."""
        with self._pool.connection() as conn:
            with conn.cursor(name=f"aryx_blocks_{run_id}") as cur:
                cur.itersize = 10_000
                cur.execute(load("select_block_keys_todo"), (run_id,))
                for row in cur:
                    yield row[0]

    def block_record_ids(self, run_id: int, key: str) -> list[int]:
        """Record ids in one block."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_block_record_ids"), (run_id, key))
                return [r[0] for r in cur.fetchall()]

    def load_records(self, ids: list[int]) -> list[ResolutionRecord]:
        """Load full records for a block or cluster by id."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_landed_by_ids"), (self._ws, ids))
                rows = cur.fetchall()
        records = []
        for record_id, payload, source_system, cleaned_at in rows:
            if isinstance(payload, str):
                payload = json.loads(payload)
            text = " ".join(str(payload.get(a, ""))
                            for a in self._key_attrs).strip()
            records.append(ResolutionRecord(
                record_id=record_id, text=text, payload=payload,
                source_system=source_system, cleaned_at=cleaned_at))
        return records

    def add_edges(self, run_id: int,
                  edges: list[tuple[int, int, float]]) -> None:
        """Persist match edges for one block."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(load("insert_match_edge"),
                                [(run_id, l, r, s) for l, r, s in edges])

    def mark_done(self, run_id: int, key: str) -> None:
        """Mark one block scored (the resume checkpoint)."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("mark_block_done"), (run_id, key))

    def edges(self, run_id: int) -> Iterator[tuple[int, int, float]]:
        """Stream match edges for the run via a server-side cursor.

        Was previously one unbatched fetchall() on the assumption "edges <<
        records; fits in memory" — a real incident broke that assumption: a
        308,104-record run produced 14,374,847 match edges (46x the record
        count), and materializing all of them (plus the caller's same-size
        pair_scores dict) as a single in-memory list caused enough memory
        pressure to crash the container mid-run, silently orphaning the job
        with no logged error. Streaming via a named cursor (same pattern as
        todo_blocks) removes the single-giant-list allocation regardless of
        how many edges a run produces.
        """
        with self._pool.connection() as conn:
            with conn.cursor(name=f"aryx_edges_{run_id}") as cur:
                cur.itersize = 10_000
                cur.execute(load("select_match_edges"), (run_id,))
                for row in cur:
                    yield (row[0], row[1], row[2])

    def close(self) -> None:
        """No-op: connections are managed by the shared pool (G12)."""
