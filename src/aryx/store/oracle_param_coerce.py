"""Coerces bind parameters and fetched values between psycopg3's and
oracledb's conventions: JSON wrapper unwrapping, boolean/empty-string
Oracle quirks, tuple-to-dict conversion for named binds, and LOB reads.

Split out of `store/oracle_pool.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

import re
from typing import Any

from aryx.store.oracle_sql_translate import _BIND_NAME_RE


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
