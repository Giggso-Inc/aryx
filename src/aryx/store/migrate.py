"""Apply SQL migrations in lexical order. Idempotent (DDL uses IF NOT EXISTS)."""
from __future__ import annotations

import logging
from pathlib import Path

import psycopg

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Constraints later migrations depend on for correctness (not just
# "nice to have"), checked by _verify_critical_constraints() after every
# migration file has run. apply_migrations()'s per-statement loop below
# deliberately swallows psycopg.Error on every statement — that's correct
# for genuinely optional statements (e.g. a missing extension), but it means
# a RAISE from inside a migration's own DO block (e.g. to reject schema
# drift) is caught and logged as a warning like anything else, not enforced.
# Verifying these here, outside that per-statement try/except, is what
# actually makes "fail startup on drift" true instead of aspirational.
# (table, constraint_name, expected `pg_get_constraintdef(oid)` text)
_CRITICAL_CONSTRAINTS: list[tuple[str, str, str]] = [
    ("aryx_ontology_type", "aryx_ontology_type_ws_name_key",
     "UNIQUE (workspace_id, name)"),
    ("aryx_ontology_type", "aryx_ontology_type_parent_ws_fkey",
     "FOREIGN KEY (workspace_id, parent_type) REFERENCES aryx_ontology_type"
     "(workspace_id, name) ON UPDATE CASCADE ON DELETE SET NULL"),
]


def _verify_critical_constraints(conn: psycopg.Connection) -> None:
    """Hard-fail if a constraint a migration depends on is missing or wrong.

    Raises RuntimeError (not psycopg.Error) so it is never caught by
    apply_migrations()'s per-statement handler and always propagates to the
    caller — the one enforcement path in this module that isn't swallowed.
    """
    with conn.cursor() as cur:
        for table, conname, expected_def in _CRITICAL_CONSTRAINTS:
            cur.execute(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = %s AND conrelid = %s::regclass",
                (conname, table),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError(
                    f"critical constraint {conname!r} missing on {table!r} "
                    "after migrations — refusing to start")
            if row[0] != expected_def:
                raise RuntimeError(
                    f"critical constraint {conname!r} on {table!r} has "
                    f"definition {row[0]!r}, expected {expected_def!r} — "
                    "schema drift, refusing to start")


def _split_statements(sql: str) -> list[str]:
    """Split on ';' but never inside a $tag$...$tag$ dollar-quoted block.

    Lets migrations use PL/pgSQL DO blocks (whose bodies contain semicolons)
    without the naive split tearing them apart.
    """
    out: list[str] = []
    buf: list[str] = []
    tag: str | None = None
    i, n = 0, len(sql)
    while i < n:
        if tag is not None:
            if sql.startswith(tag, i):
                buf.append(tag)
                i += len(tag)
                tag = None
            else:
                buf.append(sql[i])
                i += 1
            continue
        if sql[i] == "$":
            close = sql.find("$", i + 1)
            inner = sql[i + 1:close] if close != -1 else None
            if inner is not None and (inner == "" or inner.isidentifier()):
                tag = sql[i:close + 1]
                buf.append(tag)
                i = close + 1
                continue
        if sql[i] == ";":
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(sql[i])
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def apply_migrations(dsn: str) -> None:
    """Apply every .sql file under migrations/ in lexical order.

    Statements are split on ';' (respecting dollar-quoted DO blocks) and run
    one at a time, since psycopg runs a single statement per call.

    Args:
        dsn: PostgreSQL connection string.
    """
    files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    with psycopg.connect(dsn, autocommit=True) as conn:
        for path in files:
            raw = path.read_text(encoding="utf-8")
            # Strip line comments first so a ';' inside a comment can't be
            # mistaken for a statement separator.
            code = "\n".join(line.split("--", 1)[0] for line in raw.splitlines())
            statements = _split_statements(code)
            with conn.cursor() as cur:
                for statement in statements:
                    try:
                        cur.execute(statement)  # type: ignore[arg-type]
                    except psycopg.Error as exc:
                        # An optional/unavailable feature (e.g. a missing
                        # extension) must not block unrelated later migrations.
                        logger.warning("migration statement skipped file=%s error=%s",
                                       path.name, exc)
            logger.info("migration applied file=%s statements=%d", path.name, len(statements))
        _verify_critical_constraints(conn)
