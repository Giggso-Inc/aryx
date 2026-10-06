"""Initializes python-oracledb thick mode at import time, before any DB
connection is made process-wide -- see docs/oci-oracle/
ORACLE_THICK_MODE_MIGRATION_PLAN_2026-10-06.md.

Thin mode (python-oracledb's default) cannot decode "OSON version 2," a
binary JSON encoding Oracle ADB 23ai/26ai introduced -- confirmed live
across every available client version, thin mode only; not fixable by a
pip version bump. Thick mode delegates to Oracle's own Instant Client (OCI)
libraries instead, which Oracle ships in lockstep with each Database
release.

Gated behind ARYX_ORACLE_CLIENT_MODE (default "thin") -- flip back to
"thin" (or unset) to revert instantly, no rebuild needed; the Instant
Client install in the Dockerfile is unconditional, only this runtime
switch controls which mode actually runs.

init_oracle_client() is process-wide and may be called at most once per
process (a second call raises) -- idempotency-guarded here in case this
module is imported more than once within one process (e.g. test
collection).
"""
from __future__ import annotations

import logging
import os
import time
import uuid

from aryx.raven_log import raven_log

logger = logging.getLogger(__name__)

_initialized = False


def _init_thick_mode_if_configured() -> None:
    """Best-effort: a broken thick-mode init (missing/misconfigured Instant
    Client) must degrade to thin mode, not take the whole app down at
    import time. Thick mode is meant to widen what's readable (OSON v2),
    not narrow it -- a process that fails to boot reads nothing at all,
    which is strictly worse than falling back to thin and hitting the
    known, already-documented OSON v2 gap on just the affected rows."""
    global _initialized
    if _initialized:
        return
    _initialized = True
    if os.environ.get("ARYX_ORACLE_CLIENT_MODE", "thin").strip().lower() != "thick":
        return
    import oracledb  # noqa: PLC0415 -- only needed on the thick-mode path

    lib_dir = os.environ.get("ARYX_ORACLE_INSTANT_CLIENT_DIR") or os.environ.get("LD_LIBRARY_PATH")
    _t0 = time.monotonic()
    _trace_id = str(uuid.uuid4())
    try:
        oracledb.init_oracle_client(lib_dir=lib_dir)
    except Exception as exc:
        logger.exception(
            "oracledb: thick mode init FAILED (lib_dir=%s) -- falling back to "
            "thin mode. The OSON v2 gap this was meant to close "
            "(docs/oci-oracle/JSON_MERGEPATCH_OSON_V2_INCIDENT_AND_FIX_PLAN_2026-10-06.md) "
            "is back in effect until this is fixed and the process restarts.",
            lib_dir,
        )
        raven_log(
            "ERROR", "P2",
            "oracle.thick_mode.init_failed thick mode init failed, process fell back to thin mode",
            error_code="ARYX_ORACLE_THICK_MODE_INIT_FAILED",
            context={
                "dependency_name": "oracle_instant_client", "operation": "init_oracle_client",
                "duration_ms": int((time.monotonic() - _t0) * 1000), "trace_id": _trace_id,
                "result": "failed_fallback_thin", "error_class": type(exc).__name__,
                "attempt": 1, "lib_dir": lib_dir or "",
                "triggering_error": type(exc).__name__, "max_attempts": 1, "backoff_ms": 0,
                "recovery_selected": "fall_back_to_thin_mode", "fallback_target": "thin_mode",
                "exit_condition": "init_oracle_client_raised",
            },
        )
        return
    logger.info("oracledb: thick mode initialized (lib_dir=%s)", lib_dir)
    raven_log(
        "INFO", "P4", "oracle.thick_mode.initialized thick mode active for this process",
        context={"dependency_name": "oracle_instant_client", "operation": "init_oracle_client",
                  "duration_ms": int((time.monotonic() - _t0) * 1000), "trace_id": _trace_id,
                  "result": "ok", "error_class": "none", "attempt": 1, "lib_dir": lib_dir or ""},
    )


_init_thick_mode_if_configured()
