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
# Matches both ON CONFLICT DO NOTHING and ON CONFLICT DO UPDATE SET …
# The DO UPDATE clause can span multiple lines, hence re.DOTALL.
_CONFLICT_RE = re.compile(r"\s+ON CONFLICT\b[^;]*", re.IGNORECASE | re.DOTALL)
_LIMIT_OFFSET_RE = re.compile(r"\bLIMIT\s+(\d+)\s+OFFSET\s+(\d+)\b", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\bLIMIT\s+(\d+)\b", re.IGNORECASE)
_NOW_RE = re.compile(r"\bNOW\(\)", re.IGNORECASE)
# Oracle override SQL files may carry "-- ORACLE:RETURNING col1, col2" to set up
# out-vars for PL/SQL blocks where RETURNING ... INTO already appears in the SQL
# (Oracle does not support RETURNING INTO on MERGE, so override files use the
# INSERT/exception-handler pattern and carry the hint instead).
_ORACLE_RETURNING_HINT_RE = re.compile(r"--\s*ORACLE:RETURNING\s+(.+)\n", re.IGNORECASE)


def _translate_sql(sql: str, cursor: "OracleCursorWrapper") -> str:
    """Translate psycopg3 SQL to oracledb-compatible SQL.

    Mutates cursor._out_vars when RETURNING columns are detected.
    """
    import oracledb  # noqa: PLC0415

    # 0. Oracle override hint: "-- ORACLE:RETURNING col1, col2"
    #    Sets up out_vars for PL/SQL blocks that already contain RETURNING ... INTO.
    #    The step-6 guard below then skips the normal RETURNING rewrite.
    hint_m = _ORACLE_RETURNING_HINT_RE.search(sql)
    if hint_m:
        cols = [c.strip() for c in hint_m.group(1).split(",")]
        cursor._out_vars = [cursor._cur.var(oracledb.STRING) for _ in cols]
        sql = _ORACLE_RETURNING_HINT_RE.sub("", sql, count=1)

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

    # 4. NOW() → CURRENT_TIMESTAMP
    sql = _NOW_RE.sub("CURRENT_TIMESTAMP", sql)

    # 5. LIMIT n OFFSET m → OFFSET m ROWS FETCH NEXT n ROWS ONLY
    #    LIMIT n          → FETCH FIRST n ROWS ONLY
    #    Must run before RETURNING translation (order matters for regex anchors).
    sql = _LIMIT_OFFSET_RE.sub(
        lambda m: f"OFFSET {m.group(2)} ROWS FETCH NEXT {m.group(1)} ROWS ONLY", sql
    )
    sql = _LIMIT_RE.sub(lambda m: f"FETCH FIRST {m.group(1)} ROWS ONLY", sql)

    # 5. ON CONFLICT DO NOTHING / DO UPDATE → strip clause, mark cursor so ORA-00001 is swallowed.
    #    Oracle does not support ON CONFLICT syntax; duplicates are handled via ORA-00001.
    new_sql = _CONFLICT_RE.sub("", sql)
    if new_sql != sql:
        cursor._conflict_ignore = True
    sql = new_sql

    # 6. RETURNING col1, col2 → RETURNING col1, col2 INTO :r0, :r1
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

    Also handles Oracle-specific type coercions:
    - Empty strings → single space (Oracle treats '' as NULL)
    - Python bool → 'Y'/'N' (all Oracle boolean columns use CHAR(1) convention)
    - psycopg Json wrappers → serialized JSON string for CLOB columns

    Duck-typed detection: any object with both .obj and .dumps attributes is
    treated as a psycopg Json wrapper.  Works even if psycopg is not installed.
    """
    if params is None:
        return None
    if isinstance(params, bool):
        # Oracle has no BOOLEAN DDL type; all boolean columns use CHAR(1) 'Y'/'N'.
        return "Y" if params else "N"
    if isinstance(params, tuple):
        # Outer positional-params container — recurse into each value.
        return tuple(_unwrap_params(p) for p in params)
    if isinstance(params, list):
        # Inner list value (e.g. integer array for ANY/IN) — serialize to JSON
        # string so Oracle CLOB/VARCHAR2 receives a valid JSON array.
        # Oracle override SQLs use JSON_TABLE to unpack these back to rows.
        import json as _json  # noqa: PLC0415
        return _json.dumps([_unwrap_params(p) for p in params])
    if isinstance(params, dict):
        return {k: _unwrap_params(v) for k, v in params.items()}
    # Duck-type psycopg Json wrapper — serialize to JSON string so Oracle CLOB
    # receives a str, not a Python dict that oracledb cannot bind.
    # Json.__slots__ always has "dumps" (hasattr=True), but it stores None when no
    # custom serializer was passed — check callable before invoking.
    if hasattr(params, "obj") and hasattr(params, "dumps"):
        import json as _json  # noqa: PLC0415
        dumps_fn = params.dumps
        if callable(dumps_fn):
            return dumps_fn(params.obj)
        return _json.dumps(params.obj)
    # Oracle treats '' as NULL — substitute a space for empty strings so NOT
    # NULL constraints on optional text columns (description, context, …) are
    # satisfied.  The space is invisible in practice and harmless for LIKE/=.
    if params == "":
        return " "
    return params


def _read_lob(v: Any) -> Any:
    """Read oracledb LOB objects to plain Python strings on fetch.

    Oracle returns CLOB/BLOB columns as oracledb.LOB handles; Pydantic cannot
    serialize them. Duck-typed check: LOBs have a callable .read(), regular
    str/int/dict/None do not.
    """
    if v is not None and hasattr(v, "read") and callable(v.read):
        return v.read()
    return v


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
        logger.debug("execute sql=%s params=%s", oracle_sql[:120], oracle_params)
        try:
            self._cur.execute(oracle_sql, oracle_params)
        except oracledb.IntegrityError as exc:
            # ORA-00001: unique constraint violated — treat as DO NOTHING when flagged
            if self._conflict_ignore and getattr(exc, "args", (None,))[0] and "ORA-00001" in str(exc.args[0]):
                return
            raise
        except Exception as exc:
            logger.error("execute failed sql=%r params=%r error=%s", oracle_sql, oracle_params, exc)
            raise

    def executemany(self, sql: str, seq: Any) -> None:
        """Execute SQL for a sequence of parameter sets."""
        import oracledb  # noqa: PLC0415
        self._out_vars = []
        self._conflict_ignore = False
        oracle_sql = _translate_sql(sql, self)
        oracle_seq = [_unwrap_params(p) for p in seq]
        if not oracle_seq:
            return
        logger.debug("executemany sql=%s rows=%d", oracle_sql[:120], len(oracle_seq))
        try:
            self._cur.executemany(oracle_sql, oracle_seq)
        except oracledb.IntegrityError as exc:
            _args0 = getattr(exc, "args", (None,))
            _val = _args0[0] if _args0 else None
            if self._conflict_ignore and _val and "ORA-00001" in str(_val):
                return
            logger.warning("executemany IntegrityError (not swallowed) sql=%r conflict_ignore=%s exc=%s args=%r",
                           oracle_sql[:120], self._conflict_ignore, exc, exc.args)
            raise
        except Exception as exc:
            sample = oracle_seq[0] if oracle_seq else None
            logger.error("executemany failed sql=%r row0=%r error=%s", oracle_sql, sample, exc)
            raise

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
        return tuple(_read_lob(v) for v in row) if row else None

    def fetchall(self) -> list[tuple]:
        """Return all remaining rows, reading any LOB columns to strings."""
        return [tuple(_read_lob(v) for v in row) for row in self._cur.fetchall()]

    def fetchmany(self, size: int | None = None) -> list[tuple]:
        """Return up to size rows, reading any LOB columns to strings."""
        rows = self._cur.fetchmany() if size is None else self._cur.fetchmany(size)
        return [tuple(_read_lob(v) for v in row) for row in rows]

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
        from aryx.config import get_settings  # noqa: PLC0415
        settings = get_settings()
        if not settings.db_user or not settings.db_password:
            raise RuntimeError(
                "ARYX_DB_USER and ARYX_DB_PASSWORD must be set when ARYX_DB_BACKEND=oci"
            )
        logger.info("oracle_pool: creating min=%d max=%d dsn=***", min_size, max_size)
        self._pool = oracledb.create_pool(
            user=settings.db_user,
            password=settings.db_password,
            dsn=dsn,
            min=min_size,
            max=max_size,
            increment=1,
        )

    @contextmanager
    def connection(self) -> Iterator[OracleConnectionWrapper]:
        """Acquire a connection from the pool as a context manager.

        Commits on clean exit, rolls back on exception — matches the
        psycopg_pool behaviour that store classes rely on.
        """
        raw = self._pool.acquire()
        try:
            yield OracleConnectionWrapper(raw)
            raw.commit()
        except Exception:
            raw.rollback()
            raise
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
