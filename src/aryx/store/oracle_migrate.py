"""Apply Oracle ADB 23ai DDL migrations from store/migrations_oracle/."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_ORACLE_MIGRATIONS_DIR = Path(__file__).parent / "migrations_oracle"


def _split_blocks(sql: str) -> list[str]:
    """Split Oracle SQL file into executable blocks.

    Migration files use '/' on its own line as the PL/SQL block terminator
    (SQL*Plus convention). Each block is a complete unit — either a plain DDL
    statement or a full BEGIN...END PL/SQL block — and must be executed as-is
    without further splitting on ';'.
    """
    blocks: list[str] = []
    current: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped == "/":
            block = "\n".join(current).strip()
            if block:
                blocks.append(block)
            current = []
        else:
            current.append(line)
    # Trailing content after last '/' (e.g. plain ALTER TABLE without a '/')
    remainder = "\n".join(current).strip()
    if remainder:
        # Strip line comments, then split on ';' for plain SQL statements
        cleaned = "\n".join(
            ln.split("--", 1)[0] for ln in remainder.splitlines()
        )
        for stmt in cleaned.split(";"):
            s = stmt.strip()
            if s:
                blocks.append(s)
    return blocks


def apply_oracle_migrations(dsn: str) -> None:
    """Apply every .sql file under migrations_oracle/ in lexical order.

    Files use '/' as the PL/SQL block terminator. Each block is executed as
    a complete unit. DDL errors are logged as warnings and skipped — idempotent
    style mirrors the Postgres migrate.py behaviour.

    Args:
        dsn: Oracle ADB connection string (e.g. user/password@host:port/service).
    """
    import oracledb  # noqa: PLC0415

    files = sorted(_ORACLE_MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        logger.warning("oracle_migrate: no migration files found in %s", _ORACLE_MIGRATIONS_DIR)
        return

    try:
        conn = oracledb.connect(dsn)
    except Exception as exc:
        raise RuntimeError(
            "oracle_migrate: connection failed — dsn=*** "
            "(check ARYX_OCI_ADB_DSN, ARYX_DB_USER, ARYX_DB_PASSWORD)"
        ) from exc
    conn.autocommit = True
    try:
        cur = conn.cursor()
        for path in files:
            raw = path.read_text(encoding="utf-8")
            blocks = _split_blocks(raw)
            for block in blocks:
                try:
                    cur.execute(block)
                except oracledb.Error as exc:
                    logger.warning(
                        "oracle_migrate: block skipped file=%s error=%s",
                        path.name, exc,
                    )
            logger.info("oracle_migrate: applied file=%s blocks=%d",
                        path.name, len(blocks))
    finally:
        conn.close()
