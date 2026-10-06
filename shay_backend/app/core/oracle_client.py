"""Initializes python-oracledb thick mode at import time, before any DB
connection is made process-wide -- see docs/oci-oracle/
ORACLE_THICK_MODE_MIGRATION_PLAN_2026-10-06.md ("shay-api" section).

IMPORTANT: this only affects shay-api's SYNCHRONOUS Oracle engine (see the
dedicated sync/thick engine the "shay-api" section describes). shay-api's
main engine uses SQLAlchemy's async `oracle+oracledb_async` dialect, and
python-oracledb hardcodes thin mode for every async connection regardless
of this setting (oracledb/connection.py's async Connection._connect():
"mandate that thin mode is required; with asyncio, only thin mode is
supported") -- that is a library-level fact this module cannot change.
Calling init_oracle_client() here only prepares the process for the
separate sync engine to use thick mode; it does not and cannot make the
main async engine thick.

Gated behind ARYX_ORACLE_CLIENT_MODE (default "thin") -- flip back to
"thin" (or unset) to revert instantly, no rebuild needed.

init_oracle_client() is process-wide and may be called at most once per
process (a second call raises) -- idempotency-guarded here in case this
module is imported more than once within one process (e.g. test
collection).
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_initialized = False


def init_thick_mode_if_configured() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True
    if os.environ.get("ARYX_ORACLE_CLIENT_MODE", "thin").strip().lower() != "thick":
        return
    import oracledb  # noqa: PLC0415 -- only needed on the thick-mode path

    lib_dir = os.environ.get("ARYX_ORACLE_INSTANT_CLIENT_DIR") or os.environ.get("LD_LIBRARY_PATH")
    try:
        oracledb.init_oracle_client(lib_dir=lib_dir)
    except Exception:
        logger.exception(
            "oracledb: thick mode init FAILED (lib_dir=%s) -- the sync/thick "
            "Oracle path (if any code is using it) falls back to thin mode "
            "until this is fixed and the process restarts. The main async "
            "engine is unaffected either way (it is always thin, by library "
            "design).",
            lib_dir,
        )
        return
    logger.info("oracledb: thick mode initialized for shay-api's sync engine (lib_dir=%s)", lib_dir)
