"""OCI Functions Application/Function create-or-update helpers.

Split out of `worker/oci_functions_provisioner.py` (Raven Style
Compliance Plan, Phase 2b, 2026-09-03). Zero test patches against this
module — confirmed via grep.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_FN_MEMORY_MB = 512
_FN_TIMEOUT_S = 300


def _get_or_create_application(
    mgmt: Any,
    oci: Any,
    compartment_id: str,
    app_name: str,
    subnet_id: str,
) -> str:
    """Return existing Application OCID or create a new one."""
    apps = mgmt.list_applications(
        compartment_id=compartment_id, display_name=app_name
    ).data
    if apps:
        logger.info("functions application exists: %s → %s", app_name, apps[0].id)
        return apps[0].id

    app = mgmt.create_application(
        oci.functions.models.CreateApplicationDetails(
            compartment_id=compartment_id,
            display_name=app_name,
            subnet_ids=[subnet_id],
            shape="GENERIC_ARM",
        )
    ).data
    logger.info("created functions application: %s → %s", app_name, app.id)
    return app.id


def _get_or_create_function(
    mgmt: Any,
    oci: Any,
    app_id: str,
    fn_name: str,
    image_uri: str,
    fn_config: dict[str, str],
) -> str:
    """Return existing Function OCID (after updating image/config) or create a new one."""
    fns = mgmt.list_functions(application_id=app_id, display_name=fn_name).data
    if fns:
        fn_id = fns[0].id
        mgmt.update_function(
            fn_id,
            oci.functions.models.UpdateFunctionDetails(
                image=image_uri,
                config=fn_config,
            ),
        )
        logger.info("updated function: %s → %s", fn_name, fn_id)
        return fn_id

    fn = mgmt.create_function(
        oci.functions.models.CreateFunctionDetails(
            application_id=app_id,
            display_name=fn_name,
            image=image_uri,
            memory_in_mbs=_FN_MEMORY_MB,
            timeout_in_seconds=_FN_TIMEOUT_S,
            config=fn_config,
        )
    ).data
    logger.info("created function: %s → %s", fn_name, fn.id)
    return fn.id
