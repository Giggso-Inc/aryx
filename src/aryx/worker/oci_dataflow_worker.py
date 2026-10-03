"""OCI Data Flow worker — scaffold for Spark batch ingestion.

NOTE: This requires a pre-deployed PySpark application in OCI Data Flow.
Set ARYX_OCI_DATAFLOW_APP_OCID to the application OCID before using this backend.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from aryx.raven_log import current_run_id, raven_log

logger = logging.getLogger(__name__)


def submit_to_dataflow(app_ocid: str, args: list[str],
                       display_name: str = "aryx-ingest") -> str:
    """Submit a Data Flow run and return its OCID.

    Args:
        app_ocid: OCID of the pre-deployed PySpark application.
        args: CLI arguments forwarded to the Spark driver.
        display_name: Human-readable label for the run in OCI console.

    Returns:
        The run OCID (use to poll status via OCI console or SDK).
    """
    t0 = time.monotonic()
    try:
        import oci  # lazy
        from aryx.oci_client import _config
        client = oci.data_flow.DataFlowClient(config=_config())
        from aryx.config import get_settings
        settings = get_settings()
        resp = client.create_run(
            oci.data_flow.models.CreateRunDetails(
                application_id=app_ocid,
                compartment_id=settings.oci_compartment_id,
                display_name=display_name,
                arguments=args,
            )
        )
    except Exception as exc:
        raven_log("ERROR", "P2", "ingest.dispatch.failed OCI Data Flow send failed",
                  error_code="ARYX_ING_DISPATCH_FAILED",
                  context={"job_id": current_run_id(), "trace_id": current_run_id(),
                           "dependency_name": "oci_dataflow",
                           "operation": "invoke_async", "duration_ms": int((time.monotonic() - t0) * 1000),
                           "result": "error", "error_class": type(exc).__name__, "attempt": 1,
                           "triggering_error": type(exc).__name__, "max_attempts": 1, "backoff_ms": 0,
                           "recovery_selected": "none_reraised", "fallback_target": None,
                           "exit_condition": "reraised"})
        raise
    run_ocid: str = resp.data.id
    logger.info("submitted OCI Data Flow run %s app=%s", run_ocid, app_ocid)
    raven_log("DEBUG", "P4", "ingest.dispatch.sent OCI Data Flow run created",
              context={"job_id": current_run_id(), "trace_id": current_run_id(),
                       "dependency_name": "oci_dataflow", "operation": "invoke_async",
                       "duration_ms": int((time.monotonic() - t0) * 1000), "result": "ok",
                       "error_class": None, "attempt": 1,
                       "arg_count": len(args), "run_ocid": run_ocid})
    return run_ocid
