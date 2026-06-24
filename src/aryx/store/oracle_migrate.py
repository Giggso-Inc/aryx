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


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s",
                        stream=sys.stdout)
    from aryx.config import get_settings  # noqa: PLC0415
    s = get_settings()
    if not s.oci_adb_dsn:
        sys.exit("ARYX_OCI_ADB_DSN is not set — check your .env file")
    print(f"oracle_migrate: connecting  user={s.db_user}  dsn=***")
    apply_oracle_migrations(s.oci_adb_dsn)
    print("oracle_migrate: done — all migrations applied.")
