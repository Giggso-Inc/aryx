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
        default=4, description="Concurrent file-ingest workers (ThreadPoolExecutor width).")
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached Settings instance."""
    return Settings()
