"""Persistence for CSV ingestion issues: runs that were skipped / failed / had rejected rows.

Two tables (migration ``0047_csv_ingest_issues.sql``): ``aryx_csv_ingest_run`` and
``aryx_csv_ingest_reject``. Everything is scoped by ``workspace_id`` — callers pass it on every
call and rows of another workspace are never returned or touched.

A run is stored only when something needs attention (``should_record``). The original file is
kept (gzip + base64 text, size-capped) only for skipped/failed runs, so a file-level re-run
needs no re-upload. Recording is best-effort for the caller: see ``upload_hook``.
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import uuid
from typing import Any, Iterable

from aryx.csv_bml_ingestion.db import ConnectionFactory
from aryx.csv_bml_ingestion.options import IngestResult

STATE_OPEN, STATE_RESOLVED, STATE_SUPERSEDED, STATE_RETRYING = "open", "resolved", "superseded", "retrying"
MAX_FILE_MB_ENV = "ARYX_CSV_BML_MAX_STORED_FILE_MB"
_BATCH = 500

_RUN_COLS = ("run_id, job_id, source_file, table_name, status, error_code, message, rows_loaded, rows_bad, "
             "rows_rejected, rows_truncated, reject_total, reject_stored, file_size, "
             "CASE WHEN file_gz_b64 IS NULL THEN 0 ELSE 1 END, rerun_of, state, created_at")
_OPEN_COUNT = "(SELECT COUNT(*) FROM aryx_csv_ingest_reject r WHERE r.run_id = x.run_id AND r.state = 'open')"
_RUN_KEYS = ("run_id", "job_id", "source_file", "table_name", "status", "error_code", "message", "rows_loaded",
             "rows_bad", "rows_rejected", "rows_truncated", "reject_total", "reject_stored", "file_size",
             "file_kept", "rerun_of", "state", "created_at", "open_rejects")

_INSERT_RUN = (
    "INSERT INTO aryx_csv_ingest_run (run_id, workspace_id, job_id, source_file, table_name, status, error_code, "
    "message, rows_loaded, rows_bad, rows_rejected, rows_truncated, reject_total, reject_stored, file_size, "
    "file_gz_b64, rerun_of, state) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
_INSERT_REJECT = ("INSERT INTO aryx_csv_ingest_reject (run_id, workspace_id, line_no, reason_code, reason, row_json) "
                  "VALUES (%s, %s, %s, %s, %s, %s)")
_LIST_RUNS = (f"SELECT {_RUN_COLS}, {_OPEN_COUNT} FROM aryx_csv_ingest_run x WHERE workspace_id = %s "
              "ORDER BY created_at DESC FETCH FIRST {limit} ROWS ONLY")
_LIST_RUNS_JOB = (f"SELECT {_RUN_COLS}, {_OPEN_COUNT} FROM aryx_csv_ingest_run x WHERE workspace_id = %s AND job_id = %s "
                  "ORDER BY created_at DESC FETCH FIRST {limit} ROWS ONLY")
_GET_RUN = f"SELECT {_RUN_COLS}, {_OPEN_COUNT} FROM aryx_csv_ingest_run x WHERE workspace_id = %s AND run_id = %s"
_GET_FILE = "SELECT source_file, file_gz_b64 FROM aryx_csv_ingest_run WHERE workspace_id = %s AND run_id = %s"
_LIST_REJECTS = ("SELECT reject_id, line_no, reason_code, reason, row_json, state, attempts, resolved_at "
                 "FROM aryx_csv_ingest_reject WHERE workspace_id = %s AND run_id = %s{state_sql} "
                 "ORDER BY reject_id OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY")
_SET_RUN_STATE = ("UPDATE aryx_csv_ingest_run SET state = %s, updated_at = SYSTIMESTAMP "
                  "WHERE workspace_id = %s AND run_id = %s")
_CLAIM = ("UPDATE aryx_csv_ingest_reject SET state = 'retrying' "
          "WHERE workspace_id = %s AND run_id = %s AND state = 'open' "
          "AND EXISTS (SELECT 1 FROM aryx_csv_ingest_run r WHERE r.run_id = aryx_csv_ingest_reject.run_id "
          "AND r.state <> 'superseded')")
_CLAIMED = ("SELECT reject_id, line_no, reason_code, row_json FROM aryx_csv_ingest_reject "
            "WHERE workspace_id = %s AND run_id = %s AND state = 'retrying' ORDER BY reject_id")
_RESOLVE = ("UPDATE aryx_csv_ingest_reject SET state = 'resolved', attempts = attempts + 1, "
            "resolved_at = SYSTIMESTAMP WHERE workspace_id = %s AND reject_id = %s")
_REOPEN = ("UPDATE aryx_csv_ingest_reject SET state = 'open', attempts = attempts + 1, reason = %s "
           "WHERE workspace_id = %s AND reject_id = %s")
_RELEASE = "UPDATE aryx_csv_ingest_reject SET state = 'open' WHERE workspace_id = %s AND reject_id = %s"
_FINISH_STATE = ("UPDATE aryx_csv_ingest_run SET state = %s, updated_at = SYSTIMESTAMP "
                 "WHERE workspace_id = %s AND run_id = %s AND state IN ('open', 'resolved')")
_CLAIM_FILE_RERUN = ("UPDATE aryx_csv_ingest_run SET state = 'superseded', updated_at = SYSTIMESTAMP "
                     "WHERE workspace_id = %s AND run_id = %s AND state = 'open'")
_SUPERSEDE_OLDER = ("UPDATE aryx_csv_ingest_run SET state = 'superseded', updated_at = SYSTIMESTAMP "
                    "WHERE workspace_id = %s AND source_file = %s AND state = 'open' AND run_id <> %s "
                    "AND (table_name IS NULL OR table_name = %s)")
_SUPERSEDE_OLDER_UNLOADED = _SUPERSEDE_OLDER + " AND status <> 'loaded'"
_PURGE_WS = "DELETE FROM aryx_csv_ingest_run WHERE workspace_id = %s"
_PURGE_ALL = "DELETE FROM aryx_csv_ingest_run"
_OPEN_LEFT = "SELECT COUNT(*) FROM aryx_csv_ingest_reject WHERE workspace_id = %s AND run_id = %s AND state = 'open'"


def max_stored_file_bytes() -> int:
    """Size cap (of the stored text) for keeping a skipped/failed file; ``ARYX_CSV_BML_MAX_STORED_FILE_MB``."""
    try:
        return max(0, int(float(os.environ.get(MAX_FILE_MB_ENV, "20")) * 1024 * 1024))
    except ValueError:
        return 20 * 1024 * 1024


def should_record(result: IngestResult) -> bool:
    """A run is worth storing when it was not loaded cleanly."""
    return result.status != "loaded" or result.reject_total > 0 or result.rows_bad > 0 or result.rows_rejected > 0


def encode_file(data: bytes) -> str | None:
    """gzip + base64 text for storage; ``None`` when it would exceed the size cap."""
    text = base64.b64encode(gzip.compress(data)).decode("ascii")
    return text if len(text) <= max_stored_file_bytes() else None


def decode_file(text: str) -> bytes:
    """Inverse of ``encode_file``."""
    return gzip.decompress(base64.b64decode(text))


def _iso(v: Any) -> Any:
    return v.isoformat() if hasattr(v, "isoformat") else v


def _run_dict(row: tuple) -> dict[str, Any]:
    d = dict(zip(_RUN_KEYS, row))
    d["file_kept"] = bool(d["file_kept"])
    d["created_at"] = _iso(d["created_at"])
    return d


class IssueStore:
    """Reads and writes stored runs and rejected rows. All methods are workspace-scoped."""

    def __init__(self, factory: ConnectionFactory) -> None:
        self._factory = factory

    # ---- writing -----------------------------------------------------------------------------
    def record_run(self, workspace_id: int, job_id: str | None, result: IngestResult,
                   file_bytes: bytes | None = None, rerun_of: str | None = None) -> str:
        """Store ``result`` (and its rejected rows) as one run; returns the new ``run_id``.

        The original file is kept only when the run did not load (so it can be re-run as a whole).
        """
        run_id = uuid.uuid4().hex
        keep = result.status != "loaded" and file_bytes is not None
        file_text = encode_file(file_bytes) if keep else None
        message = (result.message or "")[:1000]
        if keep and file_text is None:
            message = (message + " [file too large to keep for re-run; re-upload it]").strip()[:1000]
        rows = [(run_id, workspace_id, r.line_no, r.code[:40], r.reason[:1000],
                 json.dumps(r.payload, default=str)) for r in result.reject_rows]
        state = STATE_OPEN if should_record(result) else STATE_RESOLVED
        with self._factory() as conn:
            cur = conn.cursor()
            cur.execute(_INSERT_RUN, (
                run_id, workspace_id, job_id, result.source[:256], result.table, result.status[:16],
                (result.error_code or None), message or None, result.rows_loaded, result.rows_bad,
                result.rows_rejected, result.rows_truncated, result.reject_total, len(rows),
                len(file_bytes) if file_bytes is not None else None, file_text, rerun_of, state))
            for i in range(0, len(rows), _BATCH):
                cur.executemany(_INSERT_REJECT, rows[i:i + _BATCH])
        return run_id

    def set_run_state(self, workspace_id: int, run_id: str, state: str) -> None:
        """Set a run's ``state`` (open / resolved / superseded)."""
        with self._factory() as conn:
            conn.cursor().execute(_SET_RUN_STATE, (state, workspace_id, run_id))

    def claim_for_file_rerun(self, workspace_id: int, run_id: str) -> bool:
        """Atomically move an ``open`` run to ``superseded``; True only for the one caller that got it.

        A double click (or a second browser tab) loses the race and gets False, so a file is never
        re-run twice. The caller reverts with ``set_run_state(..., "open")`` if it could not queue the job.
        """
        with self._factory() as conn:
            cur = conn.cursor()
            cur.execute(_CLAIM_FILE_RERUN, (workspace_id, run_id))
            return cur.rowcount == 1

    def supersede_older(self, workspace_id: int, source_file: str, table: str | None, keep_run_id: str = "",
                        reloaded: bool = True) -> None:
        """Mark older open runs of the same file (and table) as stale.

        ``reloaded=True``: the table's data was just replaced, so every older open run of this file is stale.
        ``reloaded=False``: a new attempt was skipped/failed and the table was NOT touched, so runs that loaded
        (whose rejected rows are still valid against the table) are kept; only older skipped/failed runs go.
        """
        with self._factory() as conn:
            conn.cursor().execute(_SUPERSEDE_OLDER if reloaded else _SUPERSEDE_OLDER_UNLOADED,
                                  (workspace_id, source_file[:256], keep_run_id, table))

    # ---- reading ------------------------------------------------------------------------------
    def list_runs(self, workspace_id: int, job_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Newest-first runs for a workspace (optionally one upload job)."""
        limit = max(1, min(int(limit), 200))
        sql, params = ((_LIST_RUNS_JOB, (workspace_id, job_id)) if job_id else (_LIST_RUNS, (workspace_id,)))
        with self._factory() as conn:
            cur = conn.cursor()
            cur.execute(sql.replace("{limit}", str(limit)), params)
            return [_run_dict(r) for r in cur.fetchall()]

    def get_run(self, workspace_id: int, run_id: str) -> dict[str, Any] | None:
        """One run, or None if it does not exist **in this workspace**."""
        with self._factory() as conn:
            cur = conn.cursor()
            cur.execute(_GET_RUN, (workspace_id, run_id))
            rows = cur.fetchall()
        return _run_dict(rows[0]) if rows else None

    def list_rejects(self, workspace_id: int, run_id: str, state: str | None = None,
                     offset: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        """Rejected rows of a run, in source order, paged."""
        limit, offset = max(1, min(int(limit), 500)), max(0, int(offset))
        sql = _LIST_REJECTS.replace("{limit}", str(limit)).replace("{offset}", str(offset))
        params: tuple = (workspace_id, run_id)
        if state:
            sql, params = sql.replace("{state_sql}", " AND state = %s"), (*params, state)
        else:
            sql = sql.replace("{state_sql}", "")
        with self._factory() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [{"reject_id": int(r[0]), "line_no": r[1], "reason_code": r[2], "reason": r[3],
                 "row": json.loads(r[4]) if r[4] else None, "state": r[5], "attempts": int(r[6]),
                 "resolved_at": _iso(r[7])} for r in rows]

    def get_file(self, workspace_id: int, run_id: str) -> tuple[str, bytes] | None:
        """``(source_file, bytes)`` of a stored failed/skipped file, or None when it was not kept."""
        with self._factory() as conn:
            cur = conn.cursor()
            cur.execute(_GET_FILE, (workspace_id, run_id))
            rows = cur.fetchall()
        if not rows or not rows[0][1]:
            return None
        return str(rows[0][0]), decode_file(rows[0][1])

    # ---- re-run building blocks (operate on an open cursor so a re-run is ONE transaction) -----
    @staticmethod
    def claim_open(cur: Any, workspace_id: int, run_id: str) -> list[dict[str, Any]]:
        """Move the run's open rejects to ``retrying`` (locking them) and return them.

        Two concurrent re-runs cannot both get the same row: the second blocks on the row locks
        until the first commits, then finds nothing in ``open``.
        """
        cur.execute(_CLAIM, (workspace_id, run_id))
        cur.execute(_CLAIMED, (workspace_id, run_id))
        return [{"reject_id": int(r[0]), "line_no": r[1], "reason_code": r[2],
                 "row": json.loads(r[3]) if r[3] else None} for r in cur.fetchall()]

    @staticmethod
    def mark_resolved(cur: Any, workspace_id: int, reject_ids: Iterable[int]) -> None:
        """Rows that were inserted by a re-run."""
        cur.executemany(_RESOLVE, [(workspace_id, i) for i in reject_ids])

    @staticmethod
    def mark_still_open(cur: Any, workspace_id: int, items: Iterable[tuple[int, str]]) -> None:
        """Rows that failed again: back to ``open`` with the new reason, attempts + 1."""
        cur.executemany(_REOPEN, [(reason[:1000], workspace_id, i) for i, reason in items])

    @staticmethod
    def release(cur: Any, workspace_id: int, reject_ids: Iterable[int]) -> None:
        """Rows that cannot be re-run as stored: back to ``open`` untouched (attempts unchanged)."""
        cur.executemany(_RELEASE, [(workspace_id, i) for i in reject_ids])

    @staticmethod
    def finish_run_if_clean(cur: Any, workspace_id: int, run_id: str) -> str:
        """Set the run ``resolved`` when no open rejects remain; returns the run's resulting state."""
        cur.execute(_OPEN_LEFT, (workspace_id, run_id))
        left = int(cur.fetchall()[0][0])
        state = STATE_OPEN if left else STATE_RESOLVED
        cur.execute(_FINISH_STATE, (state, workspace_id, run_id))       # never overrides 'superseded'
        return state


def purge_issues(factory: ConnectionFactory, workspace_id: int | None = None) -> None:
    """Delete stored issues of one workspace (``None`` = every workspace); rejected rows cascade."""
    with factory() as conn:
        cur = conn.cursor()
        if workspace_id is None:
            cur.execute(_PURGE_ALL)
        else:
            cur.execute(_PURGE_WS, (int(workspace_id),))
