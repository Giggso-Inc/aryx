"""OCI Functions worker — fire-and-forget per-document async invocation."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from aryx.raven_log import raven_log

logger = logging.getLogger(__name__)


def submit_to_oci_function(fn_ocid: str, payload: dict[str, Any]) -> None:
    """Invoke an OCI Function asynchronously (detached = fire-and-forget).

    Args:
        fn_ocid: Full OCID of the deployed OCI Function.
        payload: JSON-serialisable dict sent as the function body.
    """
    t0 = time.monotonic()
    try:
        import oci  # lazy — not installed in local dev
        from aryx.oci_client import _get_auth
        auth = _get_auth()
        if isinstance(auth, dict):
            client = oci.functions.FunctionsInvokeClient(config=auth)
        else:
            client = oci.functions.FunctionsInvokeClient(config={}, signer=auth)
        body = json.dumps(payload).encode()
        client.invoke_function(
            fn_ocid,
            invoke_function_body=body,
            fn_intent="cloudevent",
            invoke_type="detached",   # returns 202 immediately; function runs async
        )
    except Exception as exc:
        raven_log("ERROR", "P2", "ingest.dispatch.failed OCI Function send failed",
                  error_code="ARYX_ING_DISPATCH_FAILED",
                  context={"job_id": payload.get("job_id"), "trace_id": payload.get("job_id"),
                           "dependency_name": "oci_functions",
                           "operation": "invoke_async", "duration_ms": int((time.monotonic() - t0) * 1000),
                           "result": "error", "error_class": type(exc).__name__, "attempt": 1,
                           "triggering_error": type(exc).__name__, "max_attempts": 1, "backoff_ms": 0,
                           "recovery_selected": "none_reraised", "fallback_target": None,
                           "exit_condition": "reraised"})
        raise
    raven_log("DEBUG", "P4", "ingest.dispatch.sent OCI Function invoked",
              context={"job_id": payload.get("job_id"), "trace_id": payload.get("job_id"),
                       "dependency_name": "oci_functions",
                       "operation": "invoke_async", "duration_ms": int((time.monotonic() - t0) * 1000),
                       "result": "ok", "error_class": None, "attempt": 1, "payload_bytes": len(body),
                       "payload_keys": sorted(payload.keys())})
    logger.info("dispatched to OCI Function %s payload_keys=%s",
                fn_ocid, list(payload.keys()))
