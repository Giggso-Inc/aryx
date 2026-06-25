"""Lazy singleton factory for OCI service clients.

All OCI SDK imports are deferred to call time so the module is importable
without the `oci` package installed (local-mode deployments never touch this).

Auth resolution order:
  1. Instance principal  — running inside OCI (Compute, Functions, Data Flow)
  2. ~/.oci/config       — local development; default profile unless
                           OCI_CONFIG_PROFILE env var is set
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_doc_client: Any = None
_genai_client: Any = None
_fn_mgmt_client: Any = None
_signer: Any = None


def _get_auth() -> Any:
    """Return a config dict or signer; cached after first call.

    Auth resolution order:
      1. Instance principal  — running inside OCI (Compute, Functions, Data Flow)
      2. Env-var config      — ARYX_OCI_USER_OCID set; key content in ARYX_OCI_PRIVATE_KEY_CONTENT
      3. ~/.oci/config       — local dev fallback; profile from OCI_CONFIG_PROFILE
    """
    global _signer
    if _signer is not None:
        return _signer
    try:
        import oci  # noqa: PLC0415
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        logger.info("oci_client: using instance principal auth")
        _signer = signer
    except Exception:
        import oci  # noqa: PLC0415
        if os.environ.get("ARYX_OCI_USER_OCID"):
            config = {
                "user": os.environ["ARYX_OCI_USER_OCID"],
                "tenancy": os.environ["ARYX_OCI_TENANCY_OCID"],
                "fingerprint": os.environ["ARYX_OCI_FINGERPRINT"],
                "key_content": os.environ["ARYX_OCI_PRIVATE_KEY_CONTENT"],
                "region": os.environ.get("OCI_REGION", os.environ.get("ARYX_OCI_REGION", "us-chicago-1")),
            }
            oci.config.validate_config(config)
            logger.info("oci_client: using env-var auth user=%s", os.environ["ARYX_OCI_USER_OCID"])
            _signer = config
        else:
            profile = os.environ.get("OCI_CONFIG_PROFILE", "DEFAULT")
            _signer = oci.config.from_file(profile_name=profile)
            logger.info("oci_client: using ~/.oci/config profile=%s", profile)
    return _signer


def get_doc_client() -> Any:
    """Return a cached OCI Document Understanding client."""
    global _doc_client
    if _doc_client is None:
        import oci  # noqa: PLC0415
        from aryx.config import get_settings
        auth = _get_auth()
        if isinstance(auth, dict):
            _doc_client = oci.ai_document.AIServiceDocumentClient(config=auth)
        else:
            _doc_client = oci.ai_document.AIServiceDocumentClient(
                config={}, signer=auth
            )
        logger.info("oci_client: Document Understanding client ready (region=%s)",
                    get_settings().oci_region)
    return _doc_client


def get_genai_client() -> Any:
    """Return a cached OCI Generative AI Inference client."""
    global _genai_client
    if _genai_client is None:
        import oci  # noqa: PLC0415
        from aryx.config import get_settings
        settings = get_settings()
        auth = _get_auth()
        endpoint = (
            f"https://inference.generativeai.{settings.oci_region}.oci.oraclecloud.com"
        )
        if isinstance(auth, dict):
            _genai_client = oci.generative_ai_inference.GenerativeAiInferenceClient(
                config=auth, service_endpoint=endpoint
            )
        else:
            _genai_client = oci.generative_ai_inference.GenerativeAiInferenceClient(
                config={}, signer=auth, service_endpoint=endpoint
            )
        logger.info("oci_client: GenAI Inference client ready (endpoint=%s)", endpoint)
    return _genai_client


def get_fn_mgmt_client() -> Any:
    """Return a cached OCI Functions Management client."""
    global _fn_mgmt_client
    if _fn_mgmt_client is None:
        import oci  # noqa: PLC0415
        from aryx.config import get_settings
        auth = _get_auth()
        if isinstance(auth, dict):
            _fn_mgmt_client = oci.functions.FunctionsManagementClient(config=auth)
        else:
            _fn_mgmt_client = oci.functions.FunctionsManagementClient(
                config={}, signer=auth
            )
        logger.info("oci_client: Functions Management client ready (region=%s)",
                    get_settings().oci_region)
    return _fn_mgmt_client


def reset_clients() -> None:
    """Reset cached clients — used in tests to inject fresh mocks."""
    global _doc_client, _genai_client, _fn_mgmt_client, _signer
    _doc_client = None
    _genai_client = None
    _fn_mgmt_client = None
    _signer = None
