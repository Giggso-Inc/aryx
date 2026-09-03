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

from aryx.store.oracle_sql_translate import _BIND_NAME_RE, _MERGE_ON_RE, _translate_sql

logger = logging.getLogger(__name__)

_oracle_pools: dict[str, "OraclePool"] = {}
_oracle_pool_lock = threading.Lock()

# _translate_sql and its SQL-rewriting regexes moved to
# store/oracle_sql_translate.py (Raven Style Compliance Plan, Phase 2a,
# 2026-09-03) -- re-imported above since execute()/executemany() below
# still call _translate_sql and need _MERGE_ON_RE/_BIND_NAME_RE for their
# own ON-clause exclusion logic. tests/test_oracle_pool.py and
# tests/test_oracle_workspace.py's direct `from aryx.store.oracle_pool
# import _translate_sql` calls keep working via this re-export.


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


_SQL_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_SQL_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_sql_comments(sql: str) -> str:
    """Remove -- line comments and /* */ block comments from SQL text."""
    sql = _SQL_LINE_COMMENT_RE.sub("", sql)
    sql = _SQL_BLOCK_COMMENT_RE.sub("", sql)
    return sql


def _tuple_seq_to_dict(oracle_sql: str, seq: list[Any]) -> list[Any]:
    """Convert tuple rows → dicts for named-bind SQL (avoids DPY-4009).

    oracledb thin counts each :name occurrence in the SQL as a separate
    positional slot when data arrives as tuples — a MERGE with 5 named
    params repeated across ON/UPDATE/INSERT branches = 10 expected binds,
    5 provided → DPY-4009.  Dicts let oracledb deduplicate by name.
    Returns seq unchanged for positional SQL (:1, :2, …) or dict rows.

    Comments are stripped before scanning so that :name mentions inside
    -- or /* */ comment blocks (e.g. "-- Positional (:N) vars…") are not
    mistakenly treated as bind placeholders (would cause DPY-4008).
    """
    if not seq or isinstance(seq[0], dict):
        return seq
    sql_code = _strip_sql_comments(oracle_sql)
    seen: set[str] = set()
    names: list[str] = []
    for m in _BIND_NAME_RE.finditer(sql_code):
        n = m.group(1)
        if n not in seen and not n.isdigit():
            seen.add(n)
            names.append(n)
    if not names:
        return seq  # positional SQL — tuples are correct
    return [dict(zip(names, row)) if isinstance(row, (tuple, list)) else row for row in seq]


def _read_lob(v: Any) -> Any:
    """Read oracledb LOB objects to plain Python strings on fetch.

    Oracle returns CLOB/BLOB columns as oracledb.LOB handles; Pydantic cannot
    serialize them. Duck-typed check: LOBs have a callable .read(), regular
    str/int/dict/None do not.
    """
    if v is not None and hasattr(v, "read") and callable(v.read):
        return v.read()
    return v


def _restore_empty_string(v: Any) -> Any:
    """Undo the write-side '' -> ' ' substitution on fetch.

    Oracle treats '' as NULL, so _unwrap_params() writes a single space for
    any empty string param to satisfy NOT NULL columns. Without this inverse
    step on read, every originally-empty text/CLOB value comes back as a
    literal ' ' -- visible as stray whitespace, or as a truthy-but-blank
    value to any caller checking `if value:`. A genuine single-space value is
    not a realistic case (same assumption the write-side comment already
    makes), so this reversal is safe.
    """
    return "" if v == " " else v


# ── CLOB size guard ──────────────────────────────────────────────────────────

# Oracle thin client binds Python str as VARCHAR2 by default (max 32767 bytes).
# Strings longer than this must be typed as DB_TYPE_CLOB via setinputsizes()
# before execute(), otherwise the TTC layer raises ORA-03146.
_ORACLE_VARCHAR2_MAX = 32767


def _hint_clob(cursor: Any, params: Any, oracledb: Any) -> None:
    """Call setinputsizes for any string param that exceeds VARCHAR2 max length.

    Named params (dict): setinputsizes(**{name: DB_TYPE_CLOB, ...})
    Positional params (list/tuple): setinputsizes(*[DB_TYPE_CLOB or None, ...])
    No-op when params is None or contains no oversized strings.
    """
    if params is None:
        return
    if isinstance(params, dict):
        hints = {
            k: oracledb.DB_TYPE_CLOB
            for k, v in params.items()
            if isinstance(v, str) and len(v.encode("utf-8")) > _ORACLE_VARCHAR2_MAX
        }
        if hints:
            logger.debug("clob_hint named keys=%s", list(hints))
            cursor.setinputsizes(**hints)
    elif isinstance(params, (list, tuple)):
        sizes = [
            oracledb.DB_TYPE_CLOB
            if isinstance(v, str) and len(v.encode("utf-8")) > _ORACLE_VARCHAR2_MAX
            else None
            for v in params
        ]
        if any(s is not None for s in sizes):
            logger.debug("clob_hint positional count=%d", sum(1 for s in sizes if s))
            cursor.setinputsizes(*sizes)


def _coerce_clob(
    params: Any,
    cursor: Any,
    oracledb: Any,
    force: bool = False,
    exclude: "frozenset[str] | None" = None,
) -> Any:
    """Replace strings with oracledb CLOB var objects IN PLACE OF the value.

    When force=False (default): only replaces strings >32767 bytes — sufficient for
    plain INSERT/UPDATE where Oracle can coerce short VARCHAR2 to CLOB implicitly.

    When force=True: replaces ALL strings regardless of length — required for MERGE
    statements where Oracle analyses bind types across both UPDATE and INSERT branches
    simultaneously.  VARCHAR2-typed binds to CLOB columns in MERGE trigger ORA-03146
    even for short strings.

    exclude: set of named param keys that must NOT be coerced (e.g. MERGE ON-clause
    keys used as comparison predicates — Oracle raises ORA-22848 if they are CLOB).
    """
    if params is None:
        return params
    threshold = -1 if force else _ORACLE_VARCHAR2_MAX
    excl = exclude or frozenset()
    if isinstance(params, dict):
        out: dict[str, Any] = {}
        for k, v in params.items():
            if k not in excl and isinstance(v, str) and len(v.encode("utf-8")) > threshold:
                cvar = cursor.var(oracledb.DB_TYPE_CLOB)
                cvar.setvalue(0, v)
                out[k] = cvar
            else:
                out[k] = v
        return out
    if isinstance(params, (list, tuple)):
        out_list: list[Any] = []
        for v in params:
            if isinstance(v, str) and len(v.encode("utf-8")) > threshold:
                cvar = cursor.var(oracledb.DB_TYPE_CLOB)
                cvar.setvalue(0, v)
                out_list.append(cvar)
            else:
                out_list.append(v)
        return tuple(out_list) if isinstance(params, tuple) else out_list
    return params


def _hint_clob_many(
    cursor: Any,
    seq: list[Any],
    oracledb: Any,
    force_merge: bool = False,
    on_excl: "frozenset[str]" = frozenset(),
) -> None:
    """Call setinputsizes for executemany: scans ALL rows to find oversized strings.

    Necessary because different rows in the batch may have different payload sizes —
    e.g. entity attributes where some rows carry large XML/JSON content and others don't.
    One setinputsizes call covers the whole executemany batch.

    force_merge=True: hint ALL string-valued named keys (except those in on_excl) as
    DB_TYPE_CLOB regardless of length.  Required for MERGE statements — Oracle analyses
    both UPDATE and INSERT branches simultaneously, so VARCHAR2-typed binds to CLOB/JSON
    columns trigger ORA-03146 even for short strings.  on_excl must hold the ON-clause
    bind names (ORA-22848 forbids CLOB in comparison predicates).
    """
    if not seq:
        return
    first = seq[0]
    if isinstance(first, dict):
        clob_keys: set[str] = set()
        if force_merge:
            # Force-hint all string-valued keys that are not ON-clause keys.
            for row in seq:
                if isinstance(row, dict):
                    for k, v in row.items():
                        if k not in clob_keys and k not in on_excl and isinstance(v, str):
                            clob_keys.add(k)
        else:
            for row in seq:
                if isinstance(row, dict):
                    for k, v in row.items():
                        if k not in clob_keys and isinstance(v, str) and len(v.encode("utf-8")) > _ORACLE_VARCHAR2_MAX:
                            clob_keys.add(k)
        if clob_keys:
            logger.debug("clob_hint_many named keys=%s force_merge=%s", sorted(clob_keys), force_merge)
            cursor.setinputsizes(**{k: oracledb.DB_TYPE_CLOB for k in clob_keys})
    elif isinstance(first, (list, tuple)):
        n_cols = len(first)
        sizes: list[Any] = [None] * n_cols
        for row in seq:
            if isinstance(row, (list, tuple)):
                for i, v in enumerate(row):
                    if sizes[i] is None and isinstance(v, str) and len(v.encode("utf-8")) > _ORACLE_VARCHAR2_MAX:
                        sizes[i] = oracledb.DB_TYPE_CLOB
        if any(s is not None for s in sizes):
            logger.debug("clob_hint_many positional count=%d", sum(1 for s in sizes if s))
            cursor.setinputsizes(*sizes)


# ── Cursor wrapper ────────────────────────────────────────────────────────────

class OracleCursorWrapper:
    """Wraps an oracledb cursor to match the psycopg3 cursor API."""

    def __init__(self, raw_cursor: Any) -> None:
        import json as _json  # noqa: PLC0415
        import oracledb  # noqa: PLC0415

        self._cur = raw_cursor
        self._out_vars: list[Any] = []  # filled by _translate_sql for RETURNING
        self._conflict_ignore: bool = False  # set when ON CONFLICT DO NOTHING was stripped

        # Oracle 23ai native JSON columns may arrive as a Python str (JSON text)
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
        try:
            self._cur.executemany(oracle_sql, oracle_seq)
        except Exception as exc:
            logger.error("executemany_returning failed sql=%r row0=%r error=%s",
                         oracle_sql, oracle_seq[0], exc)
            raise
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


# ── Connection wrapper ────────────────────────────────────────────────────────

class OracleConnectionWrapper:
    """Wraps an oracledb connection to match the psycopg3 connection API."""

    def __init__(self, raw_conn: Any) -> None:
        self._conn = raw_conn

    @property
    def call_timeout(self) -> int:
        """Per-call timeout in milliseconds (0 = unlimited) — proxies oracledb's connection.call_timeout."""
        return self._conn.call_timeout

    @call_timeout.setter
    def call_timeout(self, value: int) -> None:
        self._conn.call_timeout = value

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
            # POOL_GETMODE_TIMEDWAIT prevents the thin pool's IndexError when all
            # connections are busy — instead of crashing, acquire() raises a proper
            # PoolTimeout after wait_timeout milliseconds.
            getmode=oracledb.POOL_GETMODE_TIMEDWAIT,
            wait_timeout=30000,  # 30 s
            # ping_interval=0: ping every connection before returning it from the
            # pool — detects stale connections (DPY-4011 / broken pipe) that Oracle
            # ADB closed server-side after idle timeout, before they reach user code.
            ping_interval=0,
        )

    @contextmanager
    def connection(self, timeout: float | None = None) -> Iterator[OracleConnectionWrapper]:
        """Acquire a connection from the pool as a context manager.

        Commits on clean exit, rolls back on exception — matches the
        psycopg_pool behaviour that store classes rely on.

        Args:
            timeout: Accepted for interface parity with
                psycopg_pool.ConnectionPool.connection() so callers written
                against that interface (e.g. best-effort background writes
                that must not block on a busy pool) don't raise TypeError
                when running against this Oracle pool instead. Not enforced
                per-call: oracledb's thin pool has no per-acquire wait
                override, only the pool-wide `wait_timeout` set at
                create_pool() time (30s here, see __init__). Worst case with
                a busy pool, a caller passing a short `timeout` waits up to
                that 30s instead — still bounded, and every current caller
                of this parameter already treats acquisition failure as
                best-effort (wrapped in try/except), so a slower-than-
                requested wait is an acceptable trade for not crashing
                outright.

        Yields:
            An `OracleConnectionWrapper` bound to a live connection checked
            out from the pool.

        Raises:
            RuntimeError: If the pool is exhausted (all connections busy
                past oracledb's own wait_timeout).
        """
        del timeout  # see docstring: accepted for interface parity, not enforced
        try:
            raw = self._pool.acquire()
        except IndexError as exc:
            # oracledb thin pool bug: raises IndexError instead of a pool
            # timeout when all connections are in use and TIMEDWAIT is not set.
            raise RuntimeError(
                "oracle_pool: connection acquire failed (pool exhausted)"
            ) from exc
        try:
            yield OracleConnectionWrapper(raw)
            raw.commit()
        except Exception as exc:
            raw.rollback()
            if "DPY-4011" in str(exc) or "Broken pipe" in str(exc):
                logger.warning(
                    "oracle_pool: connection dropped mid-query (DPY-4011) — "
                    "ping_interval=0 should prevent this on acquire; "
                    "if recurring, check ADB idle timeout or network MTU settings"
                )
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
