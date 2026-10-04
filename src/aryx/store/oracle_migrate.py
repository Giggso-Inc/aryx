"""Apply Oracle ADB 26ai DDL migrations from store/migrations_oracle/."""
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


_TRACKING_TABLE_DDL = """
CREATE TABLE aryx_schema_migrations (
    filename VARCHAR2(500) PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT SYSTIMESTAMP
)
"""


def _ensure_tracking_table(cur) -> None:
    """Idempotently create the applied-migrations tracking table.

    No ``IF NOT EXISTS`` in Oracle DDL for CREATE TABLE -- catch the
    "already exists" error the same way every other idempotent migration
    block in this file already does.
    """
    import oracledb  # noqa: PLC0415
    try:
        cur.execute(_TRACKING_TABLE_DDL)
    except oracledb.Error as exc:
        if "ORA-00955" not in str(exc):  # name already used by an existing object
            raise


def _already_applied(cur) -> set[str]:
    cur.execute("SELECT filename FROM aryx_schema_migrations")
    return {row[0] for row in cur.fetchall()}


def _mark_applied(cur, filename: str) -> None:
    cur.execute(
        "INSERT INTO aryx_schema_migrations (filename) VALUES (:1)", [filename],
    )


def apply_oracle_migrations(dsn: str) -> None:
    """Apply every not-yet-applied .sql file under migrations_oracle/, in order.

    Files use '/' as the PL/SQL block terminator. Each block is executed as
    a complete unit. DDL errors are logged as warnings and skipped — idempotent
    style mirrors the Postgres migrate.py behaviour.

    A ``aryx_schema_migrations`` tracking table (2026-10-04, §6 of
    docs/ingestion/CPQ_XML_CONFIRM_RESOLVE_PERFORMANCE_ISSUES_2026-10-04.md)
    records which filenames have already been applied, so every boot after
    the first is a true no-op for them — no execute, no catch-and-log for
    migrations already fully applied. Before this, every boot re-ran every
    file and re-caught the same "already exists/already dropped" Oracle
    errors every time, which was harmless but noisy and meant a genuinely
    new failure could blend into that same expected-error noise.

    Args:
        dsn: Oracle ADB connection string (e.g. tcps://host:port/service_name).
            User and password are read from ARYX_DB_USER / ARYX_DB_PASSWORD.
    """
    import oracledb  # noqa: PLC0415
    from aryx.config import get_settings  # noqa: PLC0415

    settings = get_settings()
    if not settings.db_user or not settings.db_password:
        raise RuntimeError(
            "oracle_migrate: ARYX_DB_USER and ARYX_DB_PASSWORD must be set"
        )

    files = sorted(_ORACLE_MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        logger.warning("oracle_migrate: no migration files found in %s", _ORACLE_MIGRATIONS_DIR)
        return

    try:
        conn = oracledb.connect(
            user=settings.db_user, password=settings.db_password, dsn=dsn
        )
    except Exception as exc:
        raise RuntimeError(
            "oracle_migrate: connection failed — dsn=*** "
            "(check ARYX_OCI_ADB_DSN, ARYX_DB_USER, ARYX_DB_PASSWORD)"
        ) from exc
    conn.autocommit = True
    try:
        cur = conn.cursor()
        _ensure_tracking_table(cur)
        applied = _already_applied(cur)
        skipped_files = 0
        for path in files:
            if path.name in applied:
                skipped_files += 1
                continue
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
            _mark_applied(cur, path.name)
            logger.info("oracle_migrate: applied file=%s blocks=%d",
                        path.name, len(blocks))
        if skipped_files:
            logger.info(
                "oracle_migrate: skipped %d already-applied file(s) (tracked in "
                "aryx_schema_migrations)", skipped_files,
            )
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s",
                        stream=sys.stdout)
    from aryx.config import get_settings  # noqa: PLC0415
    s = get_settings()
    if not s.oci_adb_dsn:
        sys.exit("ARYX_OCI_ADB_DSN is not set — check your .env file")
    logger.info("oracle_migrate: connecting  user=%s  dsn=***", s.db_user)
    apply_oracle_migrations(s.oci_adb_dsn)
    logger.info("oracle_migrate: done — all migrations applied.")
