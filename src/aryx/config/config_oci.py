"""OCI backend-toggle + per-service connection settings — a Settings mixin.

ARYX_OCI_MODE=true sets all backends to "oci" unless a per-service var
overrides it. All per-service vars default to "" (unset = defer to
oci_mode). Setting a var explicitly (e.g. ARYX_EMBED_BACKEND=local) wins
over the convenience toggle.

Split out of `config.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See `config_core.py`'s docstring for the mixin-composition
rationale.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class OciSettingsMixin(BaseSettings):
    oci_mode: bool = Field(
        default=False,
        description="Convenience: route all backends to OCI unless per-service vars override.",
    )
    oci_compartment_id: str = Field(
        default="",
        description="OCI compartment OCID. Required when any backend is set to 'oci'.",
    )
    oci_region: str = Field(
        default="us-chicago-1",
        description="OCI region identifier (e.g. us-chicago-1, eu-frankfurt-1).",
    )

    # Per-service backend selectors — "" means "defer to oci_mode".
    parse_backend: str = Field(
        default="",
        description="Document parse backend: 'local' (pymupdf) or 'oci' (Document Understanding).",
    )
    embed_backend: str = Field(
        default="",
        description=(
            "Embedding backend: 'local' (Ollama), 'oci' (OCI GenAI Cohere "
            "Embed v3), or 'gemini' (Gemini batchEmbedContents, requires "
            "ARYX_LLM_API_KEY — see docs/LLM_GEMINI_MIGRATION_PLAN.md)."
        ),
    )
    embed_model_override: str = Field(
        default="",
        description="Override embed model for any backend (empty = use backend default).",
    )
    llm_cheap_backend: str = Field(
        default="",
        description="Cheap-tier LLM backend: 'local' (broker catalog) or 'oci' (Command R).",
    )
    llm_cheap_model_override: str = Field(
        default="",
        description="Override cheap-tier model name (empty = backend default).",
    )
    llm_frontier_backend: str = Field(
        default="",
        description="Frontier-tier LLM backend: 'local' (broker catalog) or 'oci' (Command R+).",
    )
    llm_frontier_model_override: str = Field(
        default="",
        description="Override frontier-tier model name (empty = backend default).",
    )
    db_backend: str = Field(
        default="",
        description="Relational store backend: 'local' (Postgres) or 'oci' (Oracle ADB 26ai). Phase 2.",
    )
    worker_backend: str = Field(
        default="",
        description="Pipeline worker: 'local', 'oci_functions', or 'oci_dataflow'. Phase 2.",
    )
    graph_backend: str = Field(
        default="",
        description="Graph store backend: 'falkordb' or 'oci_graph' (Oracle Graph Studio). Phase 2.",
    )

    # OCI service-specific connection settings
    oci_adb_dsn: str = Field(
        default="",
        description="Oracle ADB connection string. Required when db_backend='oci'.",
    )
    db_user: str = Field(
        default="",
        description="Oracle ADB username. Required when db_backend='oci'.",
    )
    db_password: str = Field(
        default="",
        description="Oracle ADB password. Required when db_backend='oci'.",
    )
    oci_ingest_fn_id: str = Field(
        default="",
        description="OCI Function OCID for per-doc ingestion. Required when worker_backend='oci_functions'.",
    )
    oci_object_storage_namespace: str = Field(
        default="",
        description="OCI Object Storage namespace. Required for large-doc (>15 MB) Document Understanding path.",
    )
    oci_document_bucket: str = Field(
        default="aryx-doc-output",
        description="OCI Object Storage bucket for Document Understanding output.",
    )
    oci_rdf_bucket: str = Field(
        default="aryx-rdf-exports",
        description="OCI Object Storage bucket for RDF/OWL ontology exports (versioning enabled).",
    )
    oci_document_features: str = Field(
        default="TEXT_DETECTION,TABLE_DETECTION,KEY_VALUE_DETECTION",
        description="Comma-separated OCI Document Understanding feature list.",
    )
    oci_dataflow_app_id: str = Field(
        default="",
        description="OCI Data Flow application OCID. Required when worker_backend='oci_dataflow'.",
    )
