"""Core pipeline settings (DSN, graph URL, batching) — a Settings mixin.

Split out of `config.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). Pydantic v2 `BaseSettings` merges fields from every base class
into the final `Settings` class's `model_fields`, so splitting the
~90-field settings class into themed mixins is behavior-preserving —
verified empirically before this split (a throwaway 3-mixin `BaseSettings`
composition correctly merged all fields and respected the final class's
own `env_prefix`). Only the final `Settings` class in `config.py` is ever
instantiated; these mixins carry no `model_config` of their own.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class CoreSettingsMixin(BaseSettings):
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
