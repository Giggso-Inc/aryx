"""Apply Oracle ADB 26ai DDL migrations from store/migrations_oracle/."""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

from aryx.raven_log import current_run_id, raven_log

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

# Sentinel row locked with SELECT ... FOR UPDATE to serialize the two
# uvicorn workers' migration runs (PR review round 7, High): ADB restricts
# EXECUTE on DBMS_LOCK for normal schema users, so a session-level named
# lock isn't available here -- a row lock on a row we already own needs no
# extra privilege. Without this, both workers could see the same
# not-yet-applied file and run its blocks concurrently; DDL mostly survives
# that via _EXPECTED_IDEMPOTENT_ORA_CODES, but a migration file whose body
# is non-idempotent DML (a one-time data backfill with no unique
# constraint to collide on) could silently double-apply with no error at
# all. The row is a real tracking-table row, never matched by any real
# migration filename, so it sorts and reads like any other row.
_LOCK_ROW_FILENAME = "__aryx_migration_lock__"


def _ensure_lock_row(cur) -> None:
    """Idempotently insert the sentinel row that ``apply_oracle_migrations``
    locks with ``SELECT ... FOR UPDATE`` for the duration of a migration run."""
    import oracledb  # noqa: PLC0415
    try:
        cur.execute(
            "INSERT INTO aryx_schema_migrations (filename) VALUES (:1)",
            [_LOCK_ROW_FILENAME],
        )
    except oracledb.Error as exc:
        if "ORA-00001" not in str(exc):  # already inserted by an earlier boot
            raise


def _ensure_tracking_table(cur) -> None:
    """Idempotently create the applied-migrations tracking table, and add
    the ``checksum`` column to a table that already exists from before it
    was added (PR review round 5, N1 -- see this module's own docstring
    for the full rationale).

    No ``IF NOT EXISTS`` in Oracle DDL for CREATE TABLE -- catch the
    "already exists" error the same way every other idempotent migration
    block in this file already does.
    """
    # PR review round 5 (Raven logging, N4): no raven_log call existed here
    # at all -- baselined rather than fixed in an earlier round.
    import oracledb  # noqa: PLC0415
    _t0 = time.monotonic()
    try:
        cur.execute(_TRACKING_TABLE_DDL)
    except oracledb.Error as exc:
        if "ORA-00955" not in str(exc):  # name already used by an existing object
            raven_log("ERROR", "P2", "oracle_migrate.ensure_tracking_table_failed unexpected error creating tracking table",
                      context={"dependency_name": "oracle_adb", "operation": "ensure_tracking_table",
                               "duration_ms": int((time.monotonic() - _t0) * 1000), "result": "error",
                               "error_class": type(exc).__name__, "attempt": 1, "trace_id": current_run_id()})
            raise
        # Table already existed (pre-checksum) -- add the column separately.
        try:
            cur.execute(_ADD_CHECKSUM_COLUMN_DDL)
        except oracledb.Error as exc2:
            if "ORA-01430" not in str(exc2):  # column already exists
                raven_log("ERROR", "P2", "oracle_migrate.ensure_tracking_table_failed unexpected error adding checksum column",
                          context={"dependency_name": "oracle_adb", "operation": "ensure_tracking_table",
                                   "duration_ms": int((time.monotonic() - _t0) * 1000), "result": "error",
                                   "error_class": type(exc2).__name__, "attempt": 1, "trace_id": current_run_id()})
                raise
    raven_log("DEBUG", "P4", "oracle_migrate.ensure_tracking_table_ok tracking table ready",
              context={"dependency_name": "oracle_adb", "operation": "ensure_tracking_table",
                       "duration_ms": int((time.monotonic() - _t0) * 1000), "result": "ok",
                       "error_class": "", "attempt": 1, "trace_id": current_run_id()})


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
    call apply_oracle_migrations() at startup. The ``_LOCK_ROW_FILENAME``
    row lock (PR review round 7, High) now serializes their runs, so in the
    normal case only one worker is ever inside this loop at a time and this
    duplicate-insert race shouldn't occur. This catch stays as a defensive
    fallback for any caller that reaches this function outside that lock
    (e.g. a future script, a lock acquired on a dropped/recreated
    connection) -- the row they'd be racing to insert is identical (just a
    filename and checksum), so "someone already marked this" and "I'm
    marking this" have the same end state either way.

    Only ever called for a file not yet in ``applied`` -- a file whose
    checksum has drifted (PR review round 5, N1) is warned about but its
    row is deliberately left untouched, not re-inserted/updated here, so
    the drift warning fires on every subsequent boot until someone
    consciously resolves it (fixes the file back, or accepts the edit by
    updating the stored checksum directly) -- silently going quiet after
    one warning would defeat the point for something that should never
    happen in normal operation.
    """
    # PR review round 5 (Raven logging, N4): no raven_log call existed here
    # at all -- baselined rather than fixed in an earlier round.
    import oracledb  # noqa: PLC0415
    _t0 = time.monotonic()
    try:
        cur.execute(
            "INSERT INTO aryx_schema_migrations (filename, checksum) VALUES (:1, :2)",
            [filename, checksum],
        )
    except oracledb.Error as exc:
        if "ORA-00001" not in str(exc):
            raven_log("ERROR", "P2", "oracle_migrate.mark_applied_failed unexpected error marking file applied",
                      context={"dependency_name": "oracle_adb", "operation": "mark_applied",
                               "duration_ms": int((time.monotonic() - _t0) * 1000), "result": "error",
                               "error_class": type(exc).__name__, "attempt": 1, "trace_id": current_run_id(),
                               "file": filename})
            raise
        raven_log("DEBUG", "P4", "oracle_migrate.mark_applied_race concurrent duplicate insert tolerated",
                  context={"dependency_name": "oracle_adb", "operation": "mark_applied",
                           "duration_ms": int((time.monotonic() - _t0) * 1000), "result": "ok",
                           "error_class": type(exc).__name__, "attempt": 1, "trace_id": current_run_id(),
                           "file": filename})
        return
    raven_log("DEBUG", "P4", "oracle_migrate.mark_applied_ok file marked applied",
              context={"dependency_name": "oracle_adb", "operation": "mark_applied",
                       "duration_ms": int((time.monotonic() - _t0) * 1000), "result": "ok",
                       "error_class": "", "attempt": 1, "trace_id": current_run_id(),
                       "file": filename})


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
    than guessing it's safe to replay. The warning repeats every boot
    until a human clears it with ``accept_checksum_drift()`` (or
    ``python3 -m aryx.store.oracle_migrate --accept-drift <filename>``,
    PR review round 6, N2) -- the documented, supported way to say "yes,
    I know, this edit is intentional" instead of hand-editing
    ``aryx_schema_migrations`` directly.

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
        _ensure_lock_row(cur)
        # Serialize the two uvicorn workers' migration runs (PR review round
        # 7, High) behind a row lock held for the whole run, not just the
        # tracking-table bookkeeping -- autocommit must be off for the lock
        # to survive past this one statement. Re-fetch `applied` only AFTER
        # acquiring the lock: a worker that was blocked here must see what
        # the other worker just committed, not a stale pre-lock snapshot,
        # or it would redundantly re-run a file the first worker just
        # applied.
        conn.autocommit = False
        cur.execute(
            "SELECT filename FROM aryx_schema_migrations WHERE filename = :1 FOR UPDATE",
            [_LOCK_ROW_FILENAME],
        )
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
                # P2, not P1 (PR review round 6, N1): _EXPECTED_IDEMPOTENT_
                # ORA_CODES is explicitly NOT verified against every
                # migration file (see its own docstring) -- a benign code
                # that just isn't on the list yet would page at P1 every
                # single boot, on every worker, until the list is fixed.
                # P2 still surfaces it (this is a real schema-incomplete
                # condition, not nothing) without the on-call urgency a
                # known-incomplete allowlist doesn't deserve.
                raven_log(
                    "ERROR", "P2",
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
        # Commits whatever progress this run made (and releases the lock
        # row) even on an exception path -- matches the old per-statement
        # autocommit behaviour of persisting completed files rather than
        # losing them because a later file in the same run hit an
        # unexpected error.
        conn.commit()
        conn.close()


def accept_checksum_drift(dsn: str, filename: str) -> None:
    """Deliberately accept an already-applied migration file's current
    content as the new baseline, clearing the ARYX_MIGRATE_CHECKSUM_DRIFT
    warning for it (PR review round 6, N2).

    This repo does edit shipped migrations (round 5's own N1 finding cited
    real examples) -- the drift warning is supposed to make that visible,
    not make it permanently un-clearable short of hand-editing
    aryx_schema_migrations directly. This is the documented, supported way
    to say "yes, I know, this edit is intentional" instead.

    Does NOT re-run the file's SQL -- only updates the stored checksum to
    match its current content. If the edit needs its *effect* applied too
    (not just acknowledged), that is a new migration file, same as any
    other schema change; this function is purely about silencing a warning
    for an edit that was already applied by hand or doesn't need
    re-applying (e.g. a comment-only change, or one where the SQL effect
    was already achieved some other way).

    Raises FileNotFoundError if the migration file doesn't exist, and
    ValueError if it was never recorded as applied in the first place
    (nothing to accept a drift for).
    """
    import oracledb  # noqa: PLC0415
    from aryx.config import get_settings  # noqa: PLC0415

    path = _ORACLE_MIGRATIONS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"oracle_migrate: no such migration file: {filename}")
    checksum = _checksum(path.read_text(encoding="utf-8"))

    settings = get_settings()
    conn = oracledb.connect(user=settings.db_user, password=settings.db_password, dsn=dsn)
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute("SELECT checksum FROM aryx_schema_migrations WHERE filename = :1", [filename])
        row = cur.fetchone()
        if row is None:
            raise ValueError(
                f"oracle_migrate: {filename} was never recorded as applied -- "
                "nothing to accept a drift for (run apply_oracle_migrations first)"
            )
        old_checksum = row[0]
        cur.execute(
            "UPDATE aryx_schema_migrations SET checksum = :1 WHERE filename = :2",
            [checksum, filename],
        )
        logger.warning(
            "oracle_migrate: accepted checksum drift for file=%s (old=%s new=%s)",
            filename, old_checksum, checksum,
        )
        raven_log(
            "WARN", "P3", "oracle_migrate.checksum_drift_accepted operator accepted an edited migration's new content",
            context={"file": filename, "old_checksum": old_checksum, "new_checksum": checksum,
                     "result": "ok", "reason_code": "OPERATOR_ACCEPTED_DRIFT"},
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
    # --accept-drift <filename>: clear a checksum-drift warning for an
    # intentionally-edited, already-applied migration file (PR review
    # round 6, N2) -- documented here since it's the one entry point this
    # module has.
    if len(sys.argv) == 3 and sys.argv[1] == "--accept-drift":
        logger.info("oracle_migrate: accepting checksum drift for file=%s", sys.argv[2])
        accept_checksum_drift(s.oci_adb_dsn, sys.argv[2])
        logger.info("oracle_migrate: done — drift accepted.")
        sys.exit(0)
    logger.info("oracle_migrate: connecting  user=%s  dsn=***", s.db_user)
    apply_oracle_migrations(s.oci_adb_dsn)
    logger.info("oracle_migrate: done — all migrations applied.")
