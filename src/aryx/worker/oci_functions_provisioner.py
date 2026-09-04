"""Code-driven provisioning of the aryx OCI Functions Application and Function.

Idempotent: safe to run on each deployment — creates on first run, updates image
and env-var config on subsequent runs.

Usage (one-off setup or CI deploy step)::

    from aryx.worker.oci_functions_provisioner import provision_ingest_function

    fn_ocid = provision_ingest_function(
        subnet_id="ocid1.subnet.oc1.us-chicago-1.aaa...",
        image_uri="us-chicago-1.ocir.io/<ns>/aryx/aryx-ingest-fn:latest",
    )
    # Save fn_ocid as ARYX_OCI_INGEST_FN_ID in the VM .env

Auth is resolved by ``aryx.oci_client._get_auth()``:
  - Instance Principal when running inside OCI (Compute / Functions / CI runner on OCI)
  - ``~/.oci/config`` for local dev / non-OCI CI

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`oci_functions_provisioner_resources.py` (Application/Function
create-or-update) and `oci_functions_provisioner_config.py`
(`_build_fn_config`), both re-imported here. Zero whitebox test patches
exist anywhere against this module (confirmed via grep; `test_oci_backends.py`
imports both `provision_ingest_function` and `_build_fn_config` by bare
name only), so the split was purely mechanical.
"""
from __future__ import annotations

import logging

from aryx.worker.oci_functions_provisioner_config import _build_fn_config
from aryx.worker.oci_functions_provisioner_resources import (
    _get_or_create_application,
    _get_or_create_function,
)

__all__ = ["_build_fn_config", "provision_ingest_function"]

logger = logging.getLogger(__name__)

_APP_NAME = "aryx-pipeline"
_FN_NAME = "aryx-ingest-fn"


def provision_ingest_function(
    subnet_id: str,
    image_uri: str,
    app_name: str = _APP_NAME,
    fn_name: str = _FN_NAME,
) -> str:
    """Create or update the aryx ingest OCI Function. Returns function OCID.

    - Creates the Functions Application ``app_name`` in ``oci_compartment_id`` when absent.
    - Creates the Function ``fn_name`` with memory=512 MB and timeout=300 s when absent.
    - Updates the image URI and env-var config when the function already exists.

    Args:
        subnet_id: OCID of the VCN subnet the Application network-attaches to.
        image_uri: OCIR image URI, e.g. ``us-chicago-1.ocir.io/<ns>/aryx/aryx-ingest-fn:latest``.
        app_name: Functions Application display name (default ``aryx-pipeline``).
        fn_name: Function display name (default ``aryx-ingest-fn``).

    Returns:
        Function OCID — save as ``ARYX_OCI_INGEST_FN_ID`` in the VM ``.env``.
    """
    import oci  # noqa: PLC0415 — lazy: not installed in local dev
    from aryx.config import get_settings
    from aryx.oci_client import get_fn_mgmt_client

    settings = get_settings()
    mgmt = get_fn_mgmt_client()
    compartment_id = settings.oci_compartment_id

    app_id = _get_or_create_application(mgmt, oci, compartment_id, app_name, subnet_id)
    fn_config = _build_fn_config(settings)
    fn_id = _get_or_create_function(mgmt, oci, app_id, fn_name, image_uri, fn_config)

    logger.info(
        "provision complete: app=%s fn=%s ocid=%s", app_name, fn_name, fn_id
    )
    return fn_id
