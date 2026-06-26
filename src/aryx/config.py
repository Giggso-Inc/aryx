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
        default=25,
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

    csv_chunk_rows: int = Field(
        default=0,
        description=(
            "Split CSV files into chunks of this many data rows before ingesting "
            "(0 = no chunking). Useful for large CSVs where a full-file relate pass "
            "would exceed max_relate_pairs or exhaust LLM quota. "
            "Override with ARYX_CSV_CHUNK_ROWS."
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
        default=120.0,
        description="Per-call HTTP timeout in seconds for LLM requests.",
    )

    # ── Document processing ───────────────────────────────────────────────────
    per_doc_timeout: float = Field(
        default=300.0,
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached Settings instance."""
    return Settings()
