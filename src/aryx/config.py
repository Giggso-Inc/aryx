"""Application configuration loaded from the environment (12-factor)."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Aryx runtime settings sourced from ARYX_-prefixed env variables."""

    model_config = SettingsConfigDict(env_prefix="ARYX_", env_file=".env")

    rdb_dsn: str = Field(
        default="postgresql://aryx:aryx@localhost:5432/aryx",
        description="DSN for the canonical relational store (source of truth).",
    )
    graph_url: str = Field(
        default="redis://localhost:6379",
        description="Connection URL for the rebuildable FalkorDB projection.",
    )
    log_level: str = Field(default="INFO", description="Root log level.")
    batch_size: int = Field(default=500, description="Rows fetched per extract batch.")
    embed_dim: int = Field(default=768, description="Expected embedding dim; startup check fails on mismatch.")
    chunk_size: int = Field(default=1000, description="Target chunk size in characters.")
    chunk_overlap: int = Field(default=100, description="Overlap in characters between adjacent chunks.")
    worker_threads: int = Field(default=4, description="Concurrent ingest workers (ThreadPoolExecutor).")
    max_block_size: int = Field(
        default=5000,
        description="Max records per blocking group in resolution. Groups over this size are logged and skipped.",
    )
    graph_query_limit: int = Field(
        default=500,
        description="Max entity results returned by a single graph query (FalkorDB LIMIT).",
    )
    max_relate_pairs: int = Field(
        default=50,
        description="Max entity pairs evaluated for relationship inference per pipeline run.",
    )
    transitive_max_depth: int = Field(
        default=4,
        description="Max hops for transitive closure computation in edge axioms.",
    )
    rules_db_warn_threshold: int = Field(
        default=20,
        description=(
            "Warn when a workspace has more enabled rules than this. "
            "Each rule issues one DB round-trip in evaluate_workspace(); "
            "high counts saturate the connection pool under concurrent load."
        ),
    )

    # ── OCI backend toggle ────────────────────────────────────────────────────
    # ARYX_OCI_MODE=true sets all backends to "oci" unless a per-service var
    # overrides it. All per-service vars default to "" (unset = defer to
    # oci_mode). Setting a var explicitly (e.g. ARYX_EMBED_BACKEND=local) wins
    # over the convenience toggle.
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
        description="Embedding backend: 'local' (Ollama) or 'oci' (OCI GenAI Cohere Embed v3).",
    )
    embed_model_override: str = Field(
        default="",
        description="Override embed model for either backend (empty = use backend default).",
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
        description="Relational store backend: 'local' (Postgres) or 'oci' (Oracle ADB 23ai). Phase 2.",
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

    # ── Backend resolution helpers ────────────────────────────────────────────
    def _resolve(self, per_service: str, phase2_default: str = "local") -> str:
        """Return per_service value if set, else 'oci' if oci_mode, else default."""
        if per_service:
            return per_service
        return "oci" if self.oci_mode else phase2_default

    def effective_parse_backend(self) -> str:
        """Return the resolved parse backend (oci or local)."""
        return self._resolve(self.parse_backend)

    def effective_embed_backend(self) -> str:
        """Return the resolved embedding backend (oci or ollama)."""
        return self._resolve(self.embed_backend)

    def effective_llm_cheap_backend(self) -> str:
        """Return the resolved cheap-LLM backend (oci or ollama)."""
        return self._resolve(self.llm_cheap_backend)

    def effective_llm_frontier_backend(self) -> str:
        """Return the resolved frontier-LLM backend (oci or ollama)."""
        return self._resolve(self.llm_frontier_backend)

    def effective_db_backend(self) -> str:
        """Return the resolved database backend (oci or postgres)."""
        return self._resolve(self.db_backend)

    def effective_worker_backend(self) -> str:
        """Return the resolved worker backend (oci_functions or local)."""
        return self._resolve(self.worker_backend)

    def effective_graph_backend(self) -> str:
        """Return the resolved graph backend (oci_graph or falkordb)."""
        if self.graph_backend:
            return self.graph_backend
        return "oci_graph" if self.oci_mode else "falkordb"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached Settings instance."""
    return Settings()
