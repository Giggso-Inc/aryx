"""Wraps an oracledb cursor to match the psycopg3 cursor API — the actual
execute()/executemany()/fetch* call sites where this project's Oracle SQL
translation, CLOB coercion, and RETURNING-handling all come together.

Split out of `store/oracle_pool.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Iterator

from aryx.log_safe import ora_code, params_shape, rows_shape
from aryx.raven_log import raven_log, would_log

from aryx.store.oracle_clob import _coerce_clob, _hint_clob_many
from aryx.store.oracle_param_coerce import (
    _read_lob,
    _restore_empty_string,
    _strip_sql_comments,
    _tuple_seq_to_dict,
    _unwrap_params,
)
from aryx.store.oracle_sql_translate import _BIND_NAME_RE, _MERGE_ON_RE, _translate_sql

logger = logging.getLogger(__name__)

# Statements slower than this are logged at INFO (so they are dropped when the level is WARN or ERROR).
SLOW_STATEMENT_MS = 2000
_VERB_TABLE_RE = re.compile(
    r"^\s*(?:(INSERT)\s+INTO|(UPDATE)|(DELETE)\s+FROM|(MERGE)\s+INTO|(SELECT)\b.*?\bFROM)\s+([\w.\"$#]+)",
    re.I | re.S,
)


def _sql_op(sql: str) -> str:
    """SQL verb and table name only (never text, never binds): 'INSERT entities'."""
    try:
        m = _VERB_TABLE_RE.match(sql or "")
        if m:
            return f"{next(g for g in m.groups()[:5] if g).upper()} {m.group(6)}"
        return ((sql or "").split(None, 1) or ["?"])[0].upper()
    except Exception:  # noqa: BLE001
        return "?"


def _ora_code(exc: BaseException) -> str:
    """ORA-/DPY- code from an exception message ('' when none)."""
    m = re.search(r"\b(ORA|DPY)-\d{4,5}\b", str(exc))
    return m.group(0) if m else ""


def _log_stmt_ok(op: str, method: str, rows: int, t0: float) -> None:
    """DEBUG per statement; INFO when slower than SLOW_STATEMENT_MS."""
    ms = int((time.monotonic() - t0) * 1000)
    if ms >= SLOW_STATEMENT_MS:
        raven_log("INFO", "P4", "db.oracle.slow_statement slow oracle statement",
                  context={"dependency_name": "oracle_adb", "operation": op, "method": method,
                           "rows": rows, "duration_ms": ms, "threshold_ms": SLOW_STATEMENT_MS,
                           "result": "ok"})
    elif would_log("DEBUG"):
        raven_log("DEBUG", "P4", "db.oracle.statement oracle statement done",
                  context={"dependency_name": "oracle_adb", "operation": op, "method": method,
                           "rows": rows, "duration_ms": ms, "result": "ok"})


# "object does not exist / already exists" codes: callers deliberately tolerate these
# (best-effort purge steps, idempotent migrations), so they are WARN P3, not ERROR P2.
_TOLERATED_ORA = frozenset({"ORA-00942", "ORA-00955", "ORA-01418", "ORA-01430", "ORA-02289"})


def _log_stmt_failed(op: str, method: str, exc: BaseException, t0: float) -> None:
    """ERROR for a failing statement, WARN for an object-missing/exists one (no params, no row0, no SQL text)."""
    tolerated = _ora_code(exc) in _TOLERATED_ORA
    raven_log("WARN" if tolerated else "ERROR", "P3" if tolerated else "P2",
              "db.oracle.call_failed oracle statement failed",
              error_code="ARYX_DB_CALL_FAILED_TOLERATED" if tolerated else "ARYX_DB_CALL_FAILED",
              context={"dependency_name": "oracle_adb", "operation": op, "method": method,
                       "duration_ms": int((time.monotonic() - t0) * 1000), "result": "error",
                       "error_class": type(exc).__name__, "ora_code": _ora_code(exc), "attempt": 1})


class OracleCursorWrapper:
    """Wraps an oracledb cursor to match the psycopg3 cursor API."""

    def __init__(self, raw_cursor: Any) -> None:
        import json as _json  # noqa: PLC0415
        import oracledb  # noqa: PLC0415

        self._cur = raw_cursor
        self._out_vars: list[Any] = []  # filled by _translate_sql for RETURNING
        self._conflict_ignore: bool = False  # set when ON CONFLICT DO NOTHING was stripped

        # oracledb's default arraysize/prefetchrows is 100 -- far below this
        # project's batch_size convention (500, see config_core.py). arraysize
        # (not the size passed to fetchmany()) is what actually controls how
        # many rows the server sends per network round-trip; leaving it at the
        # default made streaming reads like EntityStore.list_relationships()
        # issue ~1 round-trip per 100 rows regardless of the caller's
        # fetchmany(500) batch size. Measured live: 364,454 rows took 946.87s
        # (~3,645 round-trips at ~0.26s each against Oracle Cloud); raising
        # both to 500 here (prefetchrows covers the first fetch, arraysize
        # every fetch after) cuts round-trips ~5x for every cursor made
        # through this wrapper. Callers can still override via itersize.
        self._cur.arraysize = 500
        self._cur.prefetchrows = 500

        # Oracle 26ai native JSON columns may arrive as a Python str (JSON text)
        # or as a Python dict (OSON binary), depending on how the value was stored.
        # This handler normalises all DB_TYPE_JSON fetches to Python native types so
        # callers never receive raw JSON strings from SELECT queries.
        # Note: RETURNING INTO vars are typed as STRING explicitly — this handler
        # does not fire for those; _parse_brief() handles that path.
        def _convert_json(v: Any) -> Any:
            if not isinstance(v, str):
                return v
            stripped = v.strip()
            if not stripped:
                return None
            try:
                return _json.loads(stripped)
            except _json.JSONDecodeError:
                return stripped

        def _json_output_handler(cursor: Any, metadata: Any) -> Any:
            if metadata.type_code is oracledb.DB_TYPE_JSON:
                return cursor.var(
                    oracledb.DB_TYPE_JSON,
                    arraysize=cursor.arraysize,
                    outconverter=_convert_json,
                )

        self._cur.outputtypehandler = _json_output_handler

    def execute(self, sql: str, params: Any = None) -> None:
        """Execute a single SQL statement, translating psycopg3 → Oracle."""
        import oracledb  # noqa: PLC0415
        self._out_vars = []
        self._conflict_ignore = False
        oracle_sql = _translate_sql(sql, self)
        oracle_params = _unwrap_params(params)
        if self._out_vars and oracle_params is not None:
            if isinstance(oracle_params, (list, tuple)):
                oracle_params = list(oracle_params) + self._out_vars
            elif isinstance(oracle_params, dict):
                # Named-param queries: inject out_vars as :r0, :r1, … into the dict
                oracle_params = dict(oracle_params)
                for i, v in enumerate(self._out_vars):
                    oracle_params[f"r{i}"] = v
            else:
                oracle_params = [oracle_params] + self._out_vars
        elif self._out_vars:
            oracle_params = self._out_vars
        # ORA-03146 guard: MERGE requires ALL string params bound to CLOB columns to
        # be typed as CLOB (Oracle analyses both branches before evaluating ON condition).
        # ORA-22848 guard: ON-clause params are comparison keys — must stay VARCHAR2.
        # For non-MERGE DML, only strings >32767 bytes need explicit CLOB coercion.
        _is_merge = oracle_sql.lstrip().upper().startswith("MERGE ")
        _on_excl: frozenset[str] = frozenset()
        if _is_merge:
            _m = _MERGE_ON_RE.search(oracle_sql)
            if _m:
                _on_excl = frozenset(_BIND_NAME_RE.findall(_m.group(1)))
        oracle_params = _coerce_clob(oracle_params, self._cur, oracledb, force=_is_merge, exclude=_on_excl)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("execute sql=%s params=%s", oracle_sql[:120], params_shape(oracle_params))
        _op, _t0 = _sql_op(oracle_sql), time.monotonic()
        try:
            self._cur.execute(oracle_sql, oracle_params)
        except oracledb.IntegrityError as exc:
            # ORA-00001: unique constraint violated — treat as DO NOTHING when flagged
            if self._conflict_ignore and getattr(exc, "args", (None,))[0] and "ORA-00001" in str(exc.args[0]):
                raven_log("DEBUG", "P4", "db.oracle.conflict_ignored unique violation ignored (DO NOTHING)",
                          context={"operation": _op, "ora_code": "ORA-00001", "conflict_ignore": True})
                return
            _log_stmt_failed(_op, "execute", exc, _t0)
            raise
        except Exception as exc:
            logger.error("execute failed sql=%r params=%s error=%s %s", oracle_sql, params_shape(oracle_params), type(exc).__name__, ora_code(exc))
            _log_stmt_failed(_op, "execute", exc, _t0)
            raise
        else:
            _log_stmt_ok(_op, "execute", int(getattr(self._cur, "rowcount", 0) or 0), _t0)

    def executemany(self, sql: str, seq: Any) -> None:
        """Execute SQL for a sequence of parameter sets."""
        import oracledb  # noqa: PLC0415
        self._out_vars = []
        self._conflict_ignore = False
        oracle_sql = _translate_sql(sql, self)
        oracle_seq = [_unwrap_params(p) for p in seq]
        if not oracle_seq:
            return
        oracle_seq = _tuple_seq_to_dict(oracle_sql, oracle_seq)
        # Mirror execute()'s MERGE guard: force-hint all non-ON-clause string columns
        # as DB_TYPE_CLOB so Oracle can type-check both MATCHED/NOT MATCHED branches.
        _is_merge = oracle_sql.lstrip().upper().startswith("MERGE ")
        _on_excl: frozenset[str] = frozenset()
        if _is_merge:
            _m = _MERGE_ON_RE.search(oracle_sql)
            if _m:
                _on_excl = frozenset(_BIND_NAME_RE.findall(_strip_sql_comments(_m.group(1))))
        _hint_clob_many(self._cur, oracle_seq, oracledb, force_merge=_is_merge, on_excl=_on_excl)
        logger.debug("executemany sql=%s rows=%d", oracle_sql[:120], len(oracle_seq))
        _op, _t0 = _sql_op(oracle_sql), time.monotonic()
        try:
            self._cur.executemany(oracle_sql, oracle_seq)
        except oracledb.IntegrityError as exc:
            _args0 = getattr(exc, "args", (None,))
            _val = _args0[0] if _args0 else None
            if self._conflict_ignore and _val and "ORA-00001" in str(_val):
                raven_log("DEBUG", "P4", "db.oracle.conflict_ignored unique violation ignored (DO NOTHING)",
                          context={"operation": _op, "ora_code": "ORA-00001", "conflict_ignore": True,
                                   "rows": len(oracle_seq)})
                return
            _log_stmt_failed(_op, "executemany", exc, _t0)
            logger.warning("executemany IntegrityError (not swallowed) sql=%r conflict_ignore=%s exc=%s args=%s",
                           oracle_sql[:120], self._conflict_ignore, exc,
                           [type(a).__name__ for a in exc.args])
            raise
        except Exception as exc:
            sample = oracle_seq[0] if oracle_seq else None
            logger.error("executemany failed sql=%r row0=%s error=%s %s", oracle_sql, rows_shape(sample), type(exc).__name__, ora_code(exc))
            _log_stmt_failed(_op, "executemany", exc, _t0)
            raise
        else:
            _log_stmt_ok(_op, "executemany", len(oracle_seq), _t0)

    def executemany_returning(self, sql: str, seq: Any) -> list[Any]:
        """Batch INSERT...RETURNING in one Oracle round-trip; returns scalar list.

        Uses Oracle array DML: setinputsizes binds an arraysize=N output var to
        the RETURNING INTO position so oracledb collects all N generated values
        in a single executemany call.  Only supports single-column RETURNING
        (the standard RETURNING id / RETURNING sequence.NEXTVAL case).
        """
        import oracledb  # noqa: PLC0415
        self._out_vars = []
        self._conflict_ignore = False
        oracle_seq = [_unwrap_params(p) for p in seq]
        if not oracle_seq:
            return []
        n = len(oracle_seq)
        oracle_sql = _translate_sql(sql, self)
        if not self._out_vars:
            # No RETURNING clause detected — fall back to plain executemany
            _hint_clob_many(self._cur, oracle_seq, oracledb)
            self._cur.executemany(oracle_sql, oracle_seq)
            return []
        # _translate_sql put single-value vars in self._out_vars for RETURNING INTO :5, …
        # Replace with array-sized vars so executemany collects one value per row.
        array_vars = [self._cur.var(oracledb.NUMBER, arraysize=n) for _ in self._out_vars]
        self._out_vars = []
        # oracledb requires the SAME cursor.var() instance to appear in every data row —
        # that triggers array accumulation (see python-oracledb "Returning data" docs).
        first = oracle_seq[0]
        if isinstance(first, (list, tuple)):
            oracle_seq = [row + tuple(array_vars) for row in oracle_seq]
        else:
            for row in oracle_seq:
                for i, av in enumerate(array_vars):
                    row[f"r{i}"] = av
        _hint_clob_many(self._cur, oracle_seq, oracledb)
        logger.info(
            "executemany_returning sql=%r rows=%d row0_len=%d arraysize=%d",
            oracle_sql[:120], n, len(oracle_seq[0]), array_vars[0].size,
        )
        _op, _t0 = _sql_op(oracle_sql), time.monotonic()
        try:
            self._cur.executemany(oracle_sql, oracle_seq)
        except Exception as exc:
            logger.error("executemany_returning failed sql=%r row0=%s error=%s %s",
                         oracle_sql, rows_shape(oracle_seq[0]), type(exc).__name__, ora_code(exc))
            _log_stmt_failed(_op, "executemany_returning", exc, _t0)
            raise
        else:
            _log_stmt_ok(_op, "executemany_returning", n, _t0)
        raw = array_vars[0].getvalue()
        logger.info("executemany_returning raw_ids type=%s len=%s sample=%s",
                    type(raw).__name__, len(raw) if isinstance(raw, list) else "scalar", raw if not isinstance(raw, list) else raw[:3])
        if not array_vars:
            return []
        return [int(v) for v in (raw or []) if v is not None]

    def fetchone(self) -> tuple | None:
        """Return one row; drains RETURNING output vars when present."""
        if self._out_vars:
            def _drain(v: Any) -> Any:
                raw = v.getvalue()
                if isinstance(raw, list):
                    return raw[0] if raw else None
                return raw
            vals = tuple(_drain(v) for v in self._out_vars)
            self._out_vars = []
            return vals if any(v is not None for v in vals) else None
        row = self._cur.fetchone()
        return tuple(_restore_empty_string(_read_lob(v)) for v in row) if row else None

    def fetchall(self) -> list[tuple]:
        """Return all remaining rows, reading LOB columns and restoring empty strings."""
        return [tuple(_restore_empty_string(_read_lob(v)) for v in row) for row in self._cur.fetchall()]

    def fetchmany(self, size: int | None = None) -> list[tuple]:
        """Return up to size rows, reading LOB columns and restoring empty strings."""
        rows = self._cur.fetchmany() if size is None else self._cur.fetchmany(size)
        return [tuple(_restore_empty_string(_read_lob(v)) for v in row) for row in rows]

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    @property
    def description(self) -> Any:
        """Passthrough -- oracledb's FetchInfo items expose .name like psycopg's Column."""
        return self._cur.description

    @property
    def itersize(self) -> int:
        return self._cur.arraysize

    @itersize.setter
    def itersize(self, value: int) -> None:
        self._cur.arraysize = value

    def __iter__(self) -> Iterator[tuple]:
        """Iterate rows, reading LOB columns and restoring empty strings (matches fetch*)."""
        return (tuple(_restore_empty_string(_read_lob(v)) for v in row) for row in self._cur)

    def __enter__(self) -> "OracleCursorWrapper":
        return self

    def __exit__(self, *_: Any) -> None:
        self._cur.close()
