"""OCI Data Flow worker — scaffold for Spark batch ingestion.

NOTE: This requires a pre-deployed PySpark application in OCI Data Flow.
Set ARYX_OCI_DATAFLOW_APP_OCID to the application OCID before using this backend.
"""
from __future__ import annotations

import logging
from typing import Any

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
    run_ocid: str = resp.data.id
    logger.info("submitted OCI Data Flow run %s app=%s", run_ocid, app_ocid)
    return run_ocid
