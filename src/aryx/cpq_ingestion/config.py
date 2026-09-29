"""Env-driven configuration for the cpq_ingestion pipeline.

Kept as its own small ``BaseSettings`` (rather than folding into the shared
``aryx.config.Settings``) so this module stays a self-contained, independently
reviewable addition on a fast-moving branch — it reads the same ``.env`` file
and the same ``ARYX_`` prefix, so it composes with the rest of the app's
configuration without needing changes to ``aryx/config/__init__.py``.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CpqIngestionSettings(BaseSettings):
    """Settings that select and configure the cpq_ingestion pipeline."""

    model_config = SettingsConfigDict(env_prefix="ARYX_", env_file=".env", extra="ignore")

    ingest_file_type: str = Field(
        default="",
        description=(
            "File type this run should treat as CPQ input, e.g. 'xml'. "
            "Compared case-insensitively against the uploaded file's extension. "
            "Empty disables file-type gating (the pipeline never activates)."
        ),
    )
    ingest_pipeline: str = Field(
        default="",
        description=(
            "Which ingestion pipeline to route matching files through. "
            "Set to 'cpq_ingestion' to activate this package; any other "
            "value (including empty) leaves the existing XML->CSV path unchanged."
        ),
    )
    cpq_raw_graph_enabled: bool = Field(
        default=True,
        description=(
            "Whether to project the raw knowledge graph (Pass 1: one node per "
            "XML element, nesting as CONTAINS edges) before flattening to CSV. "
            "Set to false to skip the raw-graph write and keep only the "
            "existing CSV->Resolve->Relate->curated-graph path. "
            "Env var: ARYX_CPQ_RAW_GRAPH_ENABLED."
        ),
    )
    cpq_raw_workspace_offset: int = Field(
        default=1_000_000_000,
        description=(
            "Oracle Graph backend only. aryx_graph_vertex/aryx_graph_edge key "
            "rows by a plain workspace_id column with no dedicated raw/curated "
            "split, so the raw graph is given its own workspace_id "
            "(curated_workspace_id + this offset) to avoid colliding with, or "
            "being wiped by, the curated graph's rebuild-on-clear() for the "
            "same workspace. Ignored on the FalkorDB backend, which instead "
            "uses a distinct graph name (see aryx.cpq_ingestion.naming)."
        ),
    )


@lru_cache(maxsize=1)
def get_cpq_ingestion_settings() -> CpqIngestionSettings:
    """Return a process-wide cached CpqIngestionSettings instance."""
    return CpqIngestionSettings()
