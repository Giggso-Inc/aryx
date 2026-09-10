"""Translates psycopg3-style SQL to oracledb-compatible SQL: parameter
style, LIMIT/OFFSET, RETURNING, NOW(), and ON CONFLICT.

Split out of `store/oracle_pool.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aryx.store.oracle_pool import OracleCursorWrapper

_NAMED_PARAM_RE = re.compile(r"%\((\w+)\)s")
_POS_PARAM_RE = re.compile(r"%s")
_CAST_RE = re.compile(r"::(jsonb|uuid|text|vector|int|bigint|regclass|real|float|boolean)\b", re.IGNORECASE)
_RETURNING_RE = re.compile(r"\bRETURNING\s+(.+)$", re.IGNORECASE | re.DOTALL)
# Matches both ON CONFLICT DO NOTHING and ON CONFLICT DO UPDATE SET …
# Uses a tempered greedy token to stop before RETURNING (or ;) so that
# a trailing RETURNING clause is preserved for _RETURNING_RE to process.
# Old [^;]* was too greedy — it ate through NOW()\nRETURNING, stripping
# the RETURNING clause and leaving _out_vars empty → DPY-1003.
_CONFLICT_RE = re.compile(r"\s+ON CONFLICT\b(?:(?!\bRETURNING\b)[^;])*", re.IGNORECASE | re.DOTALL)
_LIMIT_OFFSET_RE = re.compile(r"\bLIMIT\s+(:\w+|\d+)\s+OFFSET\s+(:\w+|\d+)\b", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\bLIMIT\s+(:\w+|\d+)\b", re.IGNORECASE)
_NOW_RE = re.compile(r"\bNOW\(\)", re.IGNORECASE)
# Extracts the ON clause body from a MERGE statement to identify comparison-key params.
_MERGE_ON_RE = re.compile(r"\bMERGE\b.*?\bON\s*\(([^)]+)\)", re.IGNORECASE | re.DOTALL)
_BIND_NAME_RE = re.compile(r":(\w+)")
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

    # 5. ON CONFLICT DO NOTHING → strip clause, mark cursor so ORA-00001 is
    #    swallowed (Oracle does not support ON CONFLICT syntax; duplicates
    #    are handled via ORA-00001).
    #
    #    ON CONFLICT DO UPDATE is NOT handled the same way: stripping it
    #    identically to DO NOTHING would silently reduce a real upsert to
    #    insert-or-ignore, discarding the intended update on every conflict
    #    with no error (found by post-merge review -- a systemic trap for
    #    the next such query added without an explicit Oracle MERGE
    #    override). Fail loudly instead: every DO UPDATE query needs its
    #    own Oracle override (see upsert_discovery.sql's MERGE for the
    #    established pattern) or an explicit backend branch in the caller.
    conflict_match = _CONFLICT_RE.search(sql)
    if conflict_match and re.search(r"\bDO\s+UPDATE\b", conflict_match.group(0), re.IGNORECASE):
        raise ValueError(
            "ON CONFLICT ... DO UPDATE has no safe generic Oracle translation "
            "(it would silently degrade to insert-or-ignore) -- add a "
            "queries/oracle/<name>.sql override using MERGE, or an explicit "
            "backend branch in the caller"
        )
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
        if _pos_counter[0] > 0:
            # Positional SQL (%s → :1, :2, …): continue the positional sequence so
            # cursor.var() can be appended as a tuple element in executemany() and
            # oracledb recognises it as an array DML RETURNING accumulator.
            into_clause = ", ".join(f":{_pos_counter[0] + i + 1}" for i in range(len(cols)))
        else:
            # Named SQL (%(name)s → :name): fall back to :r0, :r1, … named style.
            into_clause = ", ".join(f":r{i}" for i in range(len(cols)))
        sql = sql[:m.start()] + f"RETURNING {cols_str} INTO {into_clause}"

    return sql
