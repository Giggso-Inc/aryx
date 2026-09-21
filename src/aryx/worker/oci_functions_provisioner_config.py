"""Env-var config mapping for the provisioned OCI ingest Function.

Split out of `worker/oci_functions_provisioner.py` (Raven Style
Compliance Plan, Phase 2b, 2026-09-03). `_build_fn_config` is directly
imported (bare name, not patched) by `tests/test_oci_backends.py` —
confirmed via grep.
"""
from __future__ import annotations

from typing import Any


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
        # ── Database (Oracle ADB 26ai, TLS no-wallet) ─────────────────────────
        "ARYX_DB_BACKEND": "oci",
        "ARYX_OCI_ADB_DSN": settings.oci_adb_dsn,
        "ARYX_RDB_DSN": settings.oci_adb_dsn,
        "ARYX_DB_USER": settings.db_user,
        "ARYX_DB_PASSWORD": settings.db_password,  # nosec S106 — intentional: OCI Fn env config
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
        # ── Object Storage (large-doc >15 MB upload path + RDF exports) ────────
        "OCI_OBJECT_STORAGE_NAMESPACE": settings.oci_object_storage_namespace,
        "OCI_RDF_BUCKET": settings.oci_rdf_bucket,
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
