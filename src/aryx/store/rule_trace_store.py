"""Durable (Postgres-backed) store for CPQ rule-execution traces.

Permanent-storage side of docs/CPQ_RULE_EXPORT_AND_TRACE_TDD_PLAN.md's
feature 2. Each fired rule is written as its own small row in real time
(see migration 0037_rule_trace.sql's docstring for why — the opposite
failure shape of the aryx_discovery incident, not a repeat of it), so a
mid-session crash still leaves the partial trace durably saved.

This store is the durable destination; aryx.cpq.rule_trace.RuleTrace also
writes the same events to a local .jsonl file at the same time — neither
depends on the other completing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from aryx.queries import load
from aryx.store.pool import get_pool

logger = logging.getLogger(__name__)


class RuleTraceStore:
    """CRUD for aryx_rule_trace_session / aryx_rule_trace_entry."""

    def __init__(self, dsn: str) -> None:
        self._pool = get_pool(dsn)

    def open_session(
        self, run_id: str, workspace_id: int, catalog_prefix: str, file_key: str,
    ) -> None:
        """Create the session row if one doesn't already exist for this run_id."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    load("insert_rule_trace_session"),
                    (run_id, int(workspace_id), catalog_prefix, file_key),
                )
        logger.info(
            "rule_trace_store.open_session run_id=%s catalog_prefix=%s file_key=%s",
            run_id, catalog_prefix, file_key,
        )

    def append_entry(
        self,
        run_id: str,
        seq_no: int,
        pass_num: int,
        rule_type: str,
        rule_id: str,
        attr: str | None,
        outcome: str,
        bml_tier: str | None = None,
    ) -> None:
        """Insert one fired-rule row. Called once per rule fire, never buffered."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    load("insert_rule_trace_entry"),
                    (run_id, seq_no, pass_num, rule_type, rule_id, attr, outcome, bml_tier),
                )

    def seal_session(self, run_id: str, status: str = "post_approval") -> bool:
        """Mark a session sealed. Returns True if a still-open row was sealed."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("seal_rule_trace_session"), (status, run_id))
                sealed = cur.rowcount > 0
        if sealed:
            logger.info("rule_trace_store.seal_session run_id=%s status=%s", run_id, status)
        return sealed

    def list_entries(self, run_id: str) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_rule_trace_entries"), (run_id,))
                rows = cur.fetchall()
        return [
            {
                "seq_no": r[0], "pass_num": r[1], "rule_type": r[2], "rule_id": r[3],
                "attr": r[4], "outcome": r[5], "bml_tier": r[6], "fired_at": r[7],
            }
            for r in rows
        ]

    def sweep_orphans(self, timeout_hours: int = 24) -> list[str]:
        """Seal every session still 'open' after `timeout_hours`.

        Returns the run_ids sealed as 'orphaned_timeout' — sessions that
        never reached confirm (session.complete never became True).
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_open_rule_trace_sessions_older_than"), (cutoff,))
                rows = cur.fetchall()
        sealed: list[str] = []
        for run_id, _workspace_id, _catalog_prefix, _file_key, _started_at in rows:
            if self.seal_session(run_id, status="orphaned_timeout"):
                sealed.append(run_id)
        if sealed:
            logger.info(
                "rule_trace_store.sweep_orphans sealed=%d timeout_hours=%d",
                len(sealed), timeout_hours,
            )
        return sealed
