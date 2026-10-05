"""Apply Oracle ADB 26ai DDL migrations from store/migrations_oracle/."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from aryx.raven_log import raven_log

logger = logging.getLogger(__name__)

_ORACLE_MIGRATIONS_DIR = Path(__file__).parent / "migrations_oracle"


def _checksum(raw: str) -> str:
    """SHA-256 hex digest of a migration file's raw text content."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
    checksum VARCHAR2(64),
    applied_at TIMESTAMP DEFAULT SYSTIMESTAMP
)
"""

_ADD_CHECKSUM_COLUMN_DDL = "ALTER TABLE aryx_schema_migrations ADD (checksum VARCHAR2(64))"


def _ensure_tracking_table(cur) -> None:
    """Idempotently create the applied-migrations tracking table, and add
    the ``checksum`` column to a table that already exists from before it
    was added (PR review round 5, N1 -- see this module's own docstring
    for the full rationale).

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
        # Table already existed (pre-checksum) -- add the column separately.
        try:
            cur.execute(_ADD_CHECKSUM_COLUMN_DDL)
        except oracledb.Error as exc2:
            if "ORA-01430" not in str(exc2):  # column already exists
                raise


def _already_applied(cur) -> dict[str, str | None]:
    """Map filename -> its recorded checksum (None for a pre-checksum row)."""
    cur.execute("SELECT filename, checksum FROM aryx_schema_migrations")
    return {row[0]: row[1] for row in cur.fetchall()}


# Oracle error codes this module already knows are "already applied" noise,
# not a real failure -- confirmed from this project's own migration files
# and live boot logs (docs/ingestion/CPQ_XML_CONFIRM_RESOLVE_PERFORMANCE_
# ISSUES_2026-10-04.md §6): ORA-01430 (column already exists), ORA-00955
# (name already used by an existing object), ORA-02443 (constraint doesn't
# exist to drop), ORA-01408 (this exact column list is already indexed
# under a different name/constraint -- PR review N3: most migration files
# already self-guard this one inside their own PL/SQL EXCEPTION handler
# (`IF SQLCODE != -1408 THEN NULL`), so it never reaches Python as an
# oracledb.Error for those -- but a handful of plain, un-self-guarded DDL
# statements (e.g. 0039/0041/0042/0045/0047/0049) hit it directly, and
# without this entry here their file would never be marked applied,
# logging a spurious ERROR every single boot). ORA-00001 (unique
# constraint violated) covers an idempotent data-insert migration hitting
# a row that's already there.
#
# Deliberately a narrow, explicit allowlist rather than "any error is fine"
# (PR review M3) -- a genuinely new failure (bad SQL, a missing dependency,
# a permissions problem) must NOT be silently marked applied, or it would
# never be retried and the schema would be left permanently incomplete
# with no visible error after the first boot. This list is NOT verified
# exhaustively against every migration file in migrations_oracle/ (PR
# review N3) -- if a genuinely idempotent migration still logs an
# unexpected-failure ERROR on every boot after this ships, check its
# actual ORA code first before assuming the migration itself is broken.
_EXPECTED_IDEMPOTENT_ORA_CODES = ("ORA-01430", "ORA-00955", "ORA-02443", "ORA-01408", "ORA-00001")


def _mark_applied(cur, filename: str, checksum: str) -> None:
    """Record a file as applied, with its content checksum; tolerates a
    concurrent duplicate insert.

    aryx-api runs 2 uvicorn workers (docker-compose-oci.yml), both of which
    call apply_oracle_migrations() at startup. On the first boot after this
    tracking table ships, or whenever a release adds a new migration file,
    both workers can see the same file missing from aryx_schema_migrations
    and both attempt to apply + mark it -- the second INSERT then hits
    ORA-00001 (PR review M3). Catching it here (not re-raising, not
    retrying) is correct: the row they're racing to insert is identical
    (just a filename and checksum), so "someone already marked this" and
    "I'm marking this" have the same end state.

    Only ever called for a file not yet in ``applied`` -- a file whose
    checksum has drifted (PR review round 5, N1) is warned about but its
    row is deliberately left untouched, not re-inserted/updated here, so
    the drift warning fires on every subsequent boot until someone
    consciously resolves it (fixes the file back, or accepts the edit by
    updating the stored checksum directly) -- silently going quiet after
    one warning would defeat the point for something that should never
    happen in normal operation.
    """
    import oracledb  # noqa: PLC0415
    try:
        cur.execute(
            "INSERT INTO aryx_schema_migrations (filename, checksum) VALUES (:1, :2)",
            [filename, checksum],
        )
    except oracledb.Error as exc:
        if "ORA-00001" not in str(exc):
            raise


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

    Checksummed since PR review round 5, N1: filename-only tracking meant
    an edit to an already-applied migration file would never reach a
    database that had already recorded it, with nothing logged -- and this
    repo does edit applied migration files in practice. Each applied file's
    SHA-256 is stored alongside its filename; a mismatch on a later boot is
    logged loudly (raven_log ERROR, ``ARYX_MIGRATE_CHECKSUM_DRIFT``) but the
    file is still NOT re-run automatically -- a changed migration could be
    a non-idempotent DDL edit that would fail or do the wrong thing on a
    second run, so this surfaces the drift for a human to look at rather
    than guessing it's safe to replay.

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
            raw = path.read_text(encoding="utf-8")
            checksum = _checksum(raw)
            if path.name in applied:
                recorded = applied[path.name]
                # PR review round 5, N1: this repo DOES edit already-applied
                # migration files in practice (confirmed: graph_schema.sql
                # gained idx_graph_edge_workspace_name on 2026-09-10 after
                # already shipping; 0006_documents.sql/0007_jobs.sql each
                # have 4 commits). Filename-only tracking meant such an edit
                # would silently never reach a database that already
                # recorded the file, with nothing logged. `recorded is None`
                # covers a row written before this column existed -- not
                # drift, just unknown; backfilling it would need re-reading
                # a file version that's already gone, so it's left None and
                # not warned about once, not repeatedly.
                if recorded is not None and recorded != checksum:
                    logger.error(
                        "oracle_migrate: file=%s was already applied but its content "
                        "has changed since (checksum drift) -- NOT re-running it "
                        "(could be non-idempotent); schema may be missing this edit",
                        path.name,
                    )
                    raven_log(
                        "ERROR", "P2",
                        "oracle_migrate.checksum_drift an already-applied migration file's content changed",
                        error_code="ARYX_MIGRATE_CHECKSUM_DRIFT",
                        context={"file": path.name, "recorded_checksum": recorded,
                                 "current_checksum": checksum, "result": "not_reapplied",
                                 "reason_code": "APPLIED_FILE_EDITED_AFTER_SHIPPING"},
                    )
                skipped_files += 1
                continue
            blocks = _split_blocks(raw)
            unexpected_error = False
            for block in blocks:
                try:
                    cur.execute(block)
                except oracledb.Error as exc:
                    msg = str(exc)
                    if not any(code in msg for code in _EXPECTED_IDEMPOTENT_ORA_CODES):
                        unexpected_error = True
                    logger.warning(
                        "oracle_migrate: block skipped file=%s error=%s",
                        path.name, exc,
                    )
            if unexpected_error:
                # PR review M3: do NOT mark this file applied -- a genuine
                # failure (not just "already exists/dropped") means the
                # schema is left incomplete for this file, and the only way
                # to notice and retry is for the next boot to attempt it
                # again instead of silently skipping it forever.
                logger.error(
                    "oracle_migrate: file=%s had an unexpected (non-idempotent) "
                    "error — NOT marking applied, will retry next boot",
                    path.name,
                )
                # PR review round 5, Low: this left the schema incomplete
                # with only a plain logger.error -- no raven_log, no
                # error_code, so it couldn't be found/alerted on the same
                # way every other real failure in this codebase can be.
                raven_log(
                    "ERROR", "P1",
                    "oracle_migrate.unexpected_error migration file had a non-idempotent error, schema incomplete",
                    error_code="ARYX_MIGRATE_UNEXPECTED_ERROR",
                    context={"file": path.name, "result": "not_applied",
                             "reason_code": "NON_IDEMPOTENT_BLOCK_ERROR"},
                )
                continue
            _mark_applied(cur, path.name, checksum)
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
