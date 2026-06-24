"""OCI Functions worker — fire-and-forget per-document async invocation."""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def submit_to_oci_function(fn_ocid: str, payload: dict[str, Any]) -> None:
    """Invoke an OCI Function asynchronously (detached = fire-and-forget).

    Args:
        fn_ocid: Full OCID of the deployed OCI Function.
        payload: JSON-serialisable dict sent as the function body.
    """
    import oci  # lazy — not installed in local dev
    from aryx.oci_client import _get_auth
    auth = _get_auth()
    if isinstance(auth, dict):
        client = oci.functions.FunctionsInvokeClient(config=auth)
    else:
        client = oci.functions.FunctionsInvokeClient(config={}, signer=auth)
    client.invoke_function(
        fn_ocid,
        invoke_function_body=json.dumps(payload).encode(),
        fn_intent="cloudevent",
        invoke_type="detached",   # returns 202 immediately; function runs async
    )
    logger.info("dispatched to OCI Function %s payload_keys=%s",
                fn_ocid, list(payload.keys()))
