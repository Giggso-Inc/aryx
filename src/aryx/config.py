"""Application configuration loaded from the environment (12-factor)."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Aryx runtime settings sourced from ARYX_-prefixed env variables."""

    # extra="ignore": the .env file is shared with docker-compose services
    # (SMTP, SSO, frontend URLs, ...) — keys that aren't Aryx settings must
    # not fail validation.
    model_config = SettingsConfigDict(env_prefix="ARYX_", env_file=".env",
                                      extra="ignore")

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
        default=2000,
        description="Max entity results returned by a single graph query (FalkorDB LIMIT).",
    )
    graph_lift_mode: str = Field(
        default="all_scalars",
        description=(
            "How entity attributes are projected onto graph nodes: "
            "'all_scalars' lifts every scalar attribute as a native, queryable "
            "node property; 'off' writes only id/type/name/iri. "
            "Override with ARYX_GRAPH_LIFT_MODE."
        ),
    )
    graph_attr_value_cap: int = Field(
        default=500,
        description=(
            "Max characters for a string attribute value stored as a graph node "
            "property. Longer values are truncated in the graph projection only "
            "— the RDB (aryx_entity.attributes) keeps full fidelity. Key-like "
            "attributes (*_id, guid, variable_name, ...) are exempt because a "
            "truncated identifier silently breaks exact-match joins. "
            "Override with ARYX_GRAPH_ATTR_VALUE_CAP."
        ),
    )
    graph_lift_nested: bool = Field(
        default=True,
        description=(
            "When lifting attributes to graph node properties, JSON-stringify "
            "nested dict/list values per key (subject to the value cap). "
            "False skips nested values entirely. "
            "Override with ARYX_GRAPH_LIFT_NESTED."
        ),
    )
    max_relate_pairs: int = Field(
        default=10,
        description=(
            "Max entity pairs evaluated for relationship inference per pipeline run. "
            "Each pair costs one LLM call (~10-40s on Ollama). "
            "Override with ARYX_MAX_RELATE_PAIRS env var."
        ),
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
    max_pairs_per_block: int = Field(
        default=500,
        description=(
            "Max record pairs scored per blocking group during entity resolution. "
            "Caps pairwise work within each block (O(n²) surface). "
            "Also bounds how many records are sent for embedding per block — "
            "only the first ⌈√(2×max)⌉+2 records need vectors since the pair loop "
            "cannot reach further before hitting this cap."
        ),
    )
    relate_workers: int = Field(
        default=4,
        description=(
            "Concurrent LLM calls in the relate stage (ThreadPoolExecutor). "
            "Should match OLLAMA_NUM_PARALLEL so the Ollama queue stays full "
            "without unbounded memory use. Override with ARYX_RELATE_WORKERS."
        ),
    )
    relate_max_attrs: int = Field(
        default=15,
        description=(
            "Max entity attributes sent to the LLM per relate call. "
            "Large payloads slow inference; the first N fields are kept, "
            "with _element_type always included. Override with ARYX_RELATE_MAX_ATTRS."
        ),
    )
    relate_pair_timeout: float = Field(
        default=30.0,
        description=(
            "Max seconds _relate()/_relate_isolated() wait with no in-flight "
            "pair completing before abandoning the rest of that stage. Relate "
            "is best-effort enrichment, not a correctness requirement — "
            "_relate_isolated() (or a later ingest) still connects anything "
            "left isolated, so a stuck LLM call must not block the whole "
            "ingest run for the full ARYX_LLM_TIMEOUT. "
            "Override with ARYX_RELATE_PAIR_TIMEOUT."
        ),
    )

    extract_mention_retries: int = Field(
        default=3,
        description=(
            "Max attempts per document chunk for extract_mentions()'s LLM "
            "call before giving up on that chunk. A single malformed/ "
            "unparseable JSON response (common with local models under "
            "load) previously dropped the chunk on the first failure with "
            "no retry, silently zeroing out a document's discovered entity "
            "types if it happened to hit every chunk in one run. "
            "Override with ARYX_EXTRACT_MENTION_RETRIES."
        ),
    )
    extract_mention_retry_delay: float = Field(
        default=0.5,
        description=(
            "Base seconds between extract_mentions() retry attempts "
            "(linear backoff: delay * attempt_number). "
            "Override with ARYX_EXTRACT_MENTION_RETRY_DELAY."
        ),
    )
    csv_chunk_rows: int = Field(
        default=0,
        description=(
            "Split CSV files into chunks of this many data rows before ingesting "
            "(0 = no chunking). Useful for large CSVs where a full-file relate pass "
            "would exceed max_relate_pairs or exhaust LLM quota. "
            "Override with ARYX_CSV_CHUNK_ROWS."
        ),
    )
    xml_max_entity_types: int = Field(
        default=20,
        description=(
            "Max distinct XML element types extracted into separate CSVs per file. "
            "Named types are preferred over unnamed ones within the cap. "
            "Override with ARYX_XML_MAX_ENTITY_TYPES."
        ),
    )
    xml_max_rows_per_type: int = Field(
        default=500,
        description=(
            "Max rows kept per XML entity type after extraction. "
            "Override with ARYX_XML_MAX_ROWS_PER_TYPE."
        ),
    )
    ingest_workers: int = Field(
        default=3,
        description=(
            "Parallel workers for non-last tabular plan ingestion. "
            "The final plan always runs serially to apply FK links. "
            "Override with ARYX_INGEST_WORKERS."
        ),
    )
    ingest_relate: bool = Field(
        default=False,
        description=(
            "Enable LLM relationship inference for tabular (CSV/XML) plans. "
            "Disabled by default because large payloads (e.g. CPQ function bodies) "
            "can cause inference to hang. Override with ARYX_INGEST_RELATE=true."
        ),
    )

    # ── Entity resolution thresholds ─────────────────────────────────────────
    er_auto_merge: float = Field(
        default=0.92,
        description="Score >= this triggers automatic merge (no LLM, no human).",
    )
    er_adjudicate: float = Field(
        default=0.90,
        description="Score in [er_adjudicate, er_auto_merge) triggers LLM adjudication.",
    )
    er_review: float = Field(
        default=0.75,
        description="Score in [er_review, er_adjudicate) queues the pair for human review.",
    )
    er_exact_id_match: bool = Field(
        default=True,
        description=(
            "When every match key is an opaque identifier (id/uuid/guid/key), "
            "resolve by exact equality instead of fuzzy scoring. Fuzzy similarity "
            "is semantically invalid for ids: sequential ids like 18722401146 vs "
            "18722401147 score 0.909+ and transitively collapse whole id ranges "
            "into one entity. Set ARYX_ER_EXACT_ID_MATCH=false to restore the "
            "previous fuzzy behavior."
        ),
    )
    embed_batch_size: int = Field(
        default=50,
        description="Records per embedding batch during entity resolution.",
    )

    # ── LLM provider ─────────────────────────────────────────────────────────
    llm_provider: str = Field(
        default="ollama",
        description="LLM provider: ollama, openai, anthropic, or gemini.",
    )
    llm_base_url: str = Field(
        default="http://ollama:11434",
        description="Base URL for the configured LLM provider.",
    )
    llm_menial_model: str = Field(
        default="llama3.2:3b",
        description="Model name for routine/menial LLM calls.",
    )
    llm_reason_model: str = Field(
        default="llama3.2:3b",
        description="Model name for reasoning and adjudication calls.",
    )
    llm_api_key: str = Field(
        default="",
        description="API key for cloud LLM providers (OpenAI, Anthropic, Gemini).",
    )
    llm_timeout: float = Field(
        default=900.0,
        description="Per-call HTTP timeout in seconds for LLM requests.",
    )
    llm_num_predict: int = Field(
        default=768,
        description=(
            "Max tokens Ollama generates per JSON completion call. "
            "768 fits schema-FK responses for up to ~25 entity types. "
            "Raise to 1024+ only if schema_fk returns truncated JSON. "
            "Override with ARYX_LLM_NUM_PREDICT."
        ),
    )
    bml_use_llm: bool = Field(
        default=False,
        description=(
            "Enable Tier-2 LLM fallback for BML constraint-script evaluation "
            "(aryx.cpq.bml.BmlEvaluator). Off by default: a single slow/"
            "rate-limited call can cost up to 5 retries x llm_timeout plus "
            "backoff sleeps (tens of minutes in the worst case) INSIDE one "
            "CPQ turn, since constraint evaluation runs synchronously in the "
            "request path. Disabling Tier-2 only drops evaluation for "
            "script-backed constraints Tier-1's deterministic parser can't "
            "handle — those already fell back to 'no constraint enforced' "
            "before Tier-2 existed, so this is not a new correctness gap, "
            "just reverting to that same safe fallback. Override with "
            "ARYX_BML_USE_LLM=true once the LLM provider path is fast/"
            "reliable enough not to risk stalling a live request."
        ),
    )

    # ── Document processing ───────────────────────────────────────────────────
    per_doc_timeout: float = Field(
        default=7200.0,
        description="Wall-clock budget in seconds for a single document extraction.",
    )
    doc_workers: int = Field(
        default=1,
        description="Parallel document extraction workers (1 = sequential).",
    )

    # ── Ontology interchange ──────────────────────────────────────────────────
    ontology_enabled: bool = Field(
        default=False,
        description="Enable ontology interchange (RDF/OWL) export.",
    )
    ontology_formats: str = Field(
        default="",
        description="Comma-separated export formats (turtle, json-ld, xml, n-triples). Empty = defaults.",
    )
    ontology_base_uri: str = Field(
        default="https://aryx.local/",
        description="Base URI for ontology namespace and export.",
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
        """Return the resolved embedding backend (local, OCI, or Gemini)."""
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

    def effective_dsn(self) -> str:
        """Return the canonical DB connection string for the active backend.

        OCI deployments set ARYX_OCI_ADB_DSN but may leave ARYX_RDB_DSN at
        its Postgres default. This method resolves the right DSN so callers
        don't need to branch on the backend themselves.
        """
        if self.effective_db_backend() == "oci":
            if not self.oci_adb_dsn:
                raise RuntimeError(
                    "ARYX_OCI_ADB_DSN must be set when ARYX_DB_BACKEND=oci"
                )
            return self.oci_adb_dsn
        return self.rdb_dsn


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached Settings instance."""
    return Settings()
