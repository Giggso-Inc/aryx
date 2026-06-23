"""Oracle ADB 23ai connection pool — psycopg3-compatible interface layer.

Wraps python-oracledb so all 19 store classes work unchanged when
ARYX_DB_BACKEND=oci. The wrapper handles three translation concerns:

1. Parameter style: psycopg3 uses %s / %(name)s — oracledb uses :1 / :name
2. JSON: psycopg3 uses psycopg.types.json.Json() wrappers — oracledb accepts
   plain dicts for JSON columns natively on ADB 23ai
3. RETURNING: psycopg3 returns rows from INSERT/UPDATE RETURNING via fetchone();
   oracledb requires cursor.var() output variables and RETURNING ... INTO :var

All OCI/oracledb imports are inside function bodies — local deployments that
don't have oracledb installed never hit this module.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_oracle_pools: dict[str, "OraclePool"] = {}
_oracle_pool_lock = threading.Lock()


# ── SQL translation ──────────────────────────────────────────────────────────

_NAMED_PARAM_RE = re.compile(r"%\((\w+)\)s")
_POS_PARAM_RE = re.compile(r"%s")
_CAST_RE = re.compile(r"::(jsonb|text|vector|int|bigint|regclass|real|float|boolean)\b", re.IGNORECASE)
_RETURNING_RE = re.compile(r"\bRETURNING\s+(.+)$", re.IGNORECASE | re.DOTALL)
_CONFLICT_NOTHING_RE = re.compile(r"\s+ON CONFLICT[^;]*DO NOTHING", re.IGNORECASE)


def _translate_sql(sql: str, cursor: "OracleCursorWrapper") -> str:
    """Translate psycopg3 SQL to oracledb-compatible SQL.

    Mutates cursor._out_vars when RETURNING columns are detected.
    """
    import oracledb  # noqa: PLC0415

    # 1. Named params %(name)s → :name
    sql = _NAMED_PARAM_RE.sub(r":\1", sql)

    # 2. Positional %s → :1, :2, ...
    #    Count replacements made to track positional index.
    _pos_counter = [0]

    def _next_pos(_m: re.Match) -> str:  # type: ignore[type-arg]
        _pos_counter[0] += 1
        return f":{_pos_counter[0]}"

    sql = _POS_PARAM_RE.sub(_next_pos, sql)

    # 3. Strip Postgres type casts (::jsonb, ::text, etc.)
    sql = _CAST_RE.sub("", sql)

    # 4. ON CONFLICT DO NOTHING → strip clause, mark cursor so ORA-00001 is swallowed.
    new_sql = _CONFLICT_NOTHING_RE.sub("", sql)
    if new_sql != sql:
        cursor._conflict_ignore = True
    sql = new_sql

    # 5. RETURNING col1, col2 → RETURNING col1, col2 INTO :r0, :r1
    #    Allocate cursor.var() for each output column.
    #    Guard: check for "INTO" *after* the RETURNING keyword only —
    #    "INSERT INTO" would otherwise falsely match " INTO " in the full string.
    m = _RETURNING_RE.search(sql)
    if m and "INTO" not in sql[m.start():].upper():
        cols_str = m.group(1).strip()
        cols = [c.strip() for c in cols_str.split(",")]
        out_vars = [cursor._cur.var(oracledb.STRING) for _ in cols]
        cursor._out_vars = out_vars
        into_clause = ", ".join(f":r{i}" for i in range(len(cols)))
        sql = sql[:m.start()] + f"RETURNING {cols_str} INTO {into_clause}"

    return sql


def _unwrap_params(params: Any) -> Any:
    """Recursively unwrap psycopg Json() wrappers to native Python objects.

    Duck-typed detection: any object with both .obj and .dumps attributes is
    treated as a psycopg Json wrapper.  Works even if psycopg is not installed.
    """
    if params is None:
        return None
    if isinstance(params, (list, tuple)):
        unwrapped = [_unwrap_params(p) for p in params]
        return type(params)(unwrapped)
    if isinstance(params, dict):
        return {k: _unwrap_params(v) for k, v in params.items()}
    # Duck-type psycopg Json wrapper
    if hasattr(params, "obj") and hasattr(params, "dumps"):
        return params.obj
    return params


# ── Cursor wrapper ────────────────────────────────────────────────────────────

class OracleCursorWrapper:
    """Wraps an oracledb cursor to match the psycopg3 cursor API."""

    def __init__(self, raw_cursor: Any) -> None:
        self._cur = raw_cursor
        self._out_vars: list[Any] = []  # filled by _translate_sql for RETURNING
        self._conflict_ignore: bool = False  # set when ON CONFLICT DO NOTHING was stripped

    def execute(self, sql: str, params: Any = None) -> None:
        """Execute a single SQL statement, translating psycopg3 → Oracle."""
        import oracledb  # noqa: PLC0415
        self._out_vars = []
        self._conflict_ignore = False
        oracle_sql = _translate_sql(sql, self)
        oracle_params = _unwrap_params(params)
        if self._out_vars and oracle_params is not None:
            # Append out_vars to the params tuple/list
            if isinstance(oracle_params, (list, tuple)):
                oracle_params = list(oracle_params) + self._out_vars
            else:
                oracle_params = [oracle_params] + self._out_vars
        elif self._out_vars:
            oracle_params = self._out_vars
        try:
            self._cur.execute(oracle_sql, oracle_params)
        except oracledb.IntegrityError as exc:
            # ORA-00001: unique constraint violated — treat as DO NOTHING when flagged
            if self._conflict_ignore and getattr(exc, "args", (None,))[0] and "ORA-00001" in str(exc.args[0]):
                return
            raise

    def executemany(self, sql: str, seq: Any) -> None:
        """Execute SQL for a sequence of parameter sets."""
        self._out_vars = []
        oracle_sql = _translate_sql(sql, self)
        oracle_seq = [_unwrap_params(p) for p in seq]
        self._cur.executemany(oracle_sql, oracle_seq)

    def fetchone(self) -> tuple | None:
        """Return one row; drains RETURNING output vars when present."""
        if self._out_vars:
            vals = tuple(
                v.getvalue()[0] if isinstance(v.getvalue(), list) else v.getvalue()
                for v in self._out_vars
            )
            self._out_vars = []
            return vals if any(v is not None for v in vals) else None
        return self._cur.fetchone()

    def fetchall(self) -> list[tuple]:
        """Return all remaining rows."""
        return self._cur.fetchall()

    def fetchmany(self, size: int | None = None) -> list[tuple]:
        """Return up to size rows."""
        if size is None:
            return self._cur.fetchmany()
        return self._cur.fetchmany(size)

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    @property
    def itersize(self) -> int:
        return self._cur.arraysize

    @itersize.setter
    def itersize(self, value: int) -> None:
        self._cur.arraysize = value

    def __iter__(self) -> Iterator[tuple]:
        return iter(self._cur)

    def __enter__(self) -> "OracleCursorWrapper":
        return self

    def __exit__(self, *_: Any) -> None:
        self._cur.close()


# ── Connection wrapper ────────────────────────────────────────────────────────

class OracleConnectionWrapper:
    """Wraps an oracledb connection to match the psycopg3 connection API."""

    def __init__(self, raw_conn: Any) -> None:
        self._conn = raw_conn

    def cursor(self, name: str | None = None) -> OracleCursorWrapper:
        """Return a cursor wrapper; ``name`` is accepted but ignored (no server-side cursors)."""
        return OracleCursorWrapper(self._conn.cursor())

    def execute(self, sql: str, params: Any = None) -> OracleCursorWrapper:
        """Execute on a transient cursor (used by WorkspaceStore directly)."""
        cur = OracleCursorWrapper(self._conn.cursor())
        cur.execute(sql, params)
        return cur

    def __enter__(self) -> "OracleConnectionWrapper":
        return self

    def __exit__(self, exc_type: Any, *_: Any) -> None:
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()


# ── Pool ──────────────────────────────────────────────────────────────────────

class OraclePool:
    """oracledb connection pool with a psycopg_pool-compatible interface."""

    def __init__(self, dsn: str, min_size: int = 2, max_size: int = 10) -> None:
        import oracledb  # noqa: PLC0415
        logger.info("oracle_pool: creating min=%d max=%d dsn=***", min_size, max_size)
        self._pool = oracledb.create_pool(
            dsn=dsn,
            min=min_size,
            max=max_size,
            increment=1,
        )

    @contextmanager
    def connection(self) -> Iterator[OracleConnectionWrapper]:
        """Acquire a connection from the pool as a context manager."""
        raw = self._pool.acquire()
        try:
            yield OracleConnectionWrapper(raw)
        finally:
            self._pool.release(raw)

    def close(self) -> None:
        """Close all connections in the pool."""
        try:
            self._pool.close(force=True)
        except Exception:  # noqa: BLE001
            pass


# ── Singleton factory ─────────────────────────────────────────────────────────

def get_oracle_pool(dsn: str, min_size: int = 2, max_size: int = 10) -> OraclePool:
    """Return a cached OraclePool for the given DSN (thread-safe singleton)."""
    if dsn not in _oracle_pools:
        with _oracle_pool_lock:
            if dsn not in _oracle_pools:
                _oracle_pools[dsn] = OraclePool(dsn, min_size=min_size, max_size=max_size)
    return _oracle_pools[dsn]


def close_all_oracle() -> None:
    """Close every cached Oracle pool and clear the registry."""
    with _oracle_pool_lock:
        pools = list(_oracle_pools.values())
        _oracle_pools.clear()
    for pool in pools:
        pool.close()
    logger.info("oracle_pool: all pools closed")
