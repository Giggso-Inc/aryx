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
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_APP_NAME = "aryx-pipeline"
_FN_NAME = "aryx-ingest-fn"
_FN_MEMORY_MB = 512
_FN_TIMEOUT_S = 300


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


def _build_fn_config(settings: Any) -> dict[str, str]:
    """Build the OCI Function env-var config dict from current settings.

    Maps settings fields to the ARYX_*-prefixed env vars read by fn_handler.py.
    OCI_*-prefixed vars (Object Storage, Document Understanding) are pulled from
    the current process environment so the function mirrors the API's config.

    Returns:
        A dict of non-empty ``env_name → value`` pairs ready for the OCI Function
        ``config`` field. Empty values are excluded (OCI SDK rejects blank entries).
    """
    cfg: dict[str, str] = {
        # ── Database (Oracle ADB 23ai, TLS no-wallet) ─────────────────────────
        "ARYX_DB_BACKEND": "oci",
        "ARYX_OCI_ADB_DSN": settings.oci_adb_dsn,
        "ARYX_RDB_DSN": settings.oci_adb_dsn,
        "ARYX_DB_USER": settings.db_user,
        "ARYX_DB_PASSWORD": settings.db_password,
        # ── OCI core ──────────────────────────────────────────────────────────
        "ARYX_OCI_MODE": "true",
        "ARYX_OCI_REGION": settings.oci_region,
        "ARYX_OCI_COMPARTMENT_ID": settings.oci_compartment_id,
        # ── Embedding + LLM (OCI GenAI Cohere) ───────────────────────────────
        "ARYX_EMBED_BACKEND": "oci",
        "ARYX_LLM_CHEAP_BACKEND": "oci",
        "ARYX_LLM_FRONTIER_BACKEND": "oci",
        # ── Document Understanding ────────────────────────────────────────────
        "ARYX_PARSE_BACKEND": "oci",
        "OCI_DOCUMENT_COMPARTMENT_ID": settings.oci_compartment_id,
        "OCI_DOCUMENT_NAMESPACE": settings.oci_object_storage_namespace,
        "OCI_DOCUMENT_BUCKET": settings.oci_document_bucket,
        "OCI_DOCUMENT_FEATURES": settings.oci_document_features,
        # ── Object Storage (large-doc >15 MB upload path) ─────────────────────
        "OCI_OBJECT_STORAGE_NAMESPACE": settings.oci_object_storage_namespace,
        # ── Graph (Oracle Graph / ADB SQL-PGQ) ───────────────────────────────
        "ARYX_GRAPH_BACKEND": "oci_graph",
    }

    # Optional model overrides — only include when explicitly configured
    if settings.llm_cheap_model_override:
        cfg["ARYX_LLM_CHEAP_MODEL_OVERRIDE"] = settings.llm_cheap_model_override
    if settings.llm_frontier_model_override:
        cfg["ARYX_LLM_FRONTIER_MODEL_OVERRIDE"] = settings.llm_frontier_model_override
    if settings.embed_model_override:
        cfg["ARYX_EMBED_MODEL_OVERRIDE"] = settings.embed_model_override

    # OCI Functions rejects blank config values
    return {k: v for k, v in cfg.items() if v}
