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
    extract_mention_workers: int = Field(
        default=4, description="Thread-pool width for concurrent chunk extraction.")
    extract_mention_progress_flush_chunks: int = Field(
        default=20, description="How often (in completed chunks) extract_mentions "
        "reports incremental progress via its on_progress callback.")
    worker_threads: int = Field(
        default=4, ge=1, description="Concurrent file-ingest workers (ProcessPoolExecutor width).")
    csv_chunk_rows: int = Field(
        default=0, description="Split CSV/xlsx-derived files into chunks of this many data "
        "rows before ingesting (0 = no chunking).")
    xml_max_entity_types: int = Field(
        default=20, description="Max distinct XML element types extracted into separate "
        "CSVs per uploaded XML file.")
    xml_max_rows_per_type: int = Field(
        default=500, description="Max rows kept per XML entity type after extraction.")
    max_upload_file_mb: int = Field(
        default=50, description="Max size (MB) of a single uploaded file.")
    max_upload_total_mb: int = Field(
        default=500, description="Max combined size (MB) of one upload batch.")
    max_upload_files: int = Field(
        default=50, description="Max number of files accepted in one upload batch.")
    graph_query_timeout: int = Field(
        default=30_000,
        description=(
            "Per-query timeout in milliseconds passed to GraphReader._query(). "
            "FalkorDB's own built-in default is 5000ms, which can be too short "
            "for relationship-traversal queries on large, heavily-linked "
            "workspaces. Set to 0 to disable the override and fall back to "
            "FalkorDB's own default (passed as None, not a literal 0ms, which "
            "would fail every query instantly). "
            "Override with ARYX_GRAPH_QUERY_TIMEOUT."
        ),
    )
    graph_query_limit: int = Field(
        default=2000,
        description="Max entity results returned by a single graph query (FalkorDB LIMIT). "
        "Override with ARYX_GRAPH_QUERY_LIMIT.",
    )
    identifier_lookup_enabled: bool = Field(
        default=True,
        description=(
            "Kill switch for GraphReader.find_entity_by_attribute_value(), the "
            "last-resort fallback in retrieve.py's _lookup() that matches a "
            "search term against ANY entity property, not just e.name. An "
            "entity's e.name is chosen from a single hardcoded priority list "
            "(aryx.explore._NAME_KEYS) — a row with two equally-real "
            "identifiers (e.g. an FSC and an NSN column) can only ever be "
            "found by whichever field won that list, even though both "
            "identify the same row. Override with ARYX_IDENTIFIER_LOOKUP_ENABLED."
        ),
    )
    identifier_min_length: int = Field(
        default=6,
        description=(
            "Minimum length for a search term to be treated as "
            "'identifier-shaped' and trigger the attribute-value lookup "
            "fallback above. Purely a cost gate — short/common words never "
            "reach the property scan — never a restriction on which fields "
            "are searchable. Override with ARYX_IDENTIFIER_MIN_LENGTH."
        ),
    )
    identifier_lookup_limit: int = Field(
        default=10,
        description="Max entities returned by find_entity_by_attribute_value(). "
        "Override with ARYX_IDENTIFIER_LOOKUP_LIMIT.",
    )
    ingest_workers: int = Field(
        default=3, ge=1,
        description=(
            "Thread-pool width for concurrent non-last-plan processing in "
            "ingest_confirmed() (doc_discovery.py) — the Docs-tab confirm "
            "flow. All but the last approved file/plan run concurrently "
            "(land+resolve only, no graph write); the last plan alone runs "
            "afterward and does the single graph projection. Must be >= 1 — "
            "ThreadPoolExecutor(max_workers=0) raises ValueError at "
            "construction time. Override with ARYX_INGEST_WORKERS."
        ),
    )
    max_block_size: int = Field(
        default=5000, ge=1,
        description=(
            "Max records per blocking group in entity resolution "
            "(resolution/classical.py's block()). Groups over this size are "
            "skipped with a WARNING to prevent O(n^2) pairwise-scoring "
            "blowup on degenerate data. Must be >= 1 — a value of 0 would "
            "cause every non-empty block to be skipped, silently dropping "
            "all resolution. Override with ARYX_MAX_BLOCK_SIZE."
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached Settings instance."""
    return Settings()
