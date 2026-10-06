"""Initializes python-oracledb thick mode at import time, before any DB
connection is made process-wide -- see docs/oci-oracle/
ORACLE_THICK_MODE_MIGRATION_PLAN_2026-10-06.md ("shay-api" section).

shay-api's Oracle engine (app/core/database.py) is a plain synchronous
SQLAlchemy engine, wrapped in AsyncSessionShim so request-path code keeps
using `await db.execute(...)` unchanged -- see async_session_shim.py.
python-oracledb hardcodes thin mode for any asyncio connection, so this
conversion away from `create_async_engine`/`oracle+oracledb_async` was a
prerequisite for thick mode to be usable here at all (confirmed live via a
DPY-2019 crash with the old async engine).

This module's own fallback (when ARYX_ORACLE_CLIENT_MODE is unset) is
"thin", but docker-compose-oci.yml sets the shipped default to "thick" for
this service -- flip ARYX_ORACLE_CLIENT_MODE to "thin" to revert instantly,
no rebuild needed.

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


def _first_path_entry(value: str | None) -> str | None:
    """LD_LIBRARY_PATH may be a colon-separated list; init_oracle_client()
    takes a single directory and fails (then falls back to thin) if handed
    the whole list verbatim. Only the fallback path needs this:
    ARYX_ORACLE_INSTANT_CLIENT_DIR is always a single directory by contract."""
    if not value:
        return None
    return value.split(":", 1)[0] or None


def init_thick_mode_if_configured() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True
    if os.environ.get("ARYX_ORACLE_CLIENT_MODE", "thin").strip().lower() != "thick":
        return
    import oracledb  # noqa: PLC0415 -- only needed on the thick-mode path

    lib_dir = os.environ.get("ARYX_ORACLE_INSTANT_CLIENT_DIR") or _first_path_entry(
        os.environ.get("LD_LIBRARY_PATH")
    )
    try:
        oracledb.init_oracle_client(lib_dir=lib_dir)
    except Exception:
        # raven_log() is not a shay_backend dependency (confirmed: not in
        # requirements.txt) -- this logger.exception() is this service's
        # only failure signal for a silent fallback-to-thin, unlike api's
        # equivalent path which also emits a raven_log ERROR/P2 event.
        # Accepted asymmetry until raven-logger is added to this service.
        logger.exception(
            "oracledb: thick mode init FAILED (lib_dir=%s) -- falling back "
            "to thin mode. The OSON v2 gap this was meant to close "
            "(docs/oci-oracle/JSON_MERGEPATCH_OSON_V2_INCIDENT_AND_FIX_PLAN_2026-10-06.md) "
            "is back in effect until this is fixed and the process restarts.",
            lib_dir,
        )
        return
    logger.info("oracledb: thick mode initialized (lib_dir=%s)", lib_dir)
