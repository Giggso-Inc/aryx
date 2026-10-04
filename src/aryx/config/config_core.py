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
    cpq_structural_leaf_fold_enabled: bool = Field(
        default=True,
        description=(
            "Fold structural-leaf XML tags (§1 Tier 1) onto their parent node "
            "instead of landing/resolving them as their own dataset. PR review "
            "N1: new behavior-changing fixes should ship with an opt-out, even "
            "when believed safe. Set ARYX_CPQ_STRUCTURAL_LEAF_FOLD_ENABLED=false "
            "to restore the previous behavior (every XML tag lands and resolves "
            "regardless of shape) if this is ever suspected of dropping or "
            "misplacing data on some real-world document shape not covered by "
            "tests/cpq_ingestion/test_structural_leaf.py."
        ),
    )
    cpq_force_exact_enabled: bool = Field(
        default=True,
        description=(
            "Allow resolve_run()'s force_exact override (§1 Tier 2) to take "
            "effect at all. Independently of this flag, force_exact is only "
            "ever honored when _key_selectivity() confirms near-total "
            "uniqueness (er_force_exact_min_selectivity, PR review M2) -- this "
            "flag is a second, coarser kill switch on top of that check, for "
            "disabling the mechanism entirely without needing to reason about "
            "the selectivity threshold. Set "
            "ARYX_CPQ_FORCE_EXACT_ENABLED=false to restore the previous "
            "behavior (a generic-fallback match key always uses the normal "
            "fuzzy/chunked path, same as before this PR)."
        ),
    )
    landing_batch_size: int = Field(
        default=500,
        description=(
            "Rows per executemany() flush in BatchSink (discover.py's landing write). "
            "Separate from batch_size (entity writes / CLI tools) because this is "
            "specifically the write-path batch for aryx_landed_record — a 500-row Oracle "
            "executemany was measured at ~2.4s in a 2026-10-04 live confirm, implying "
            "per-round-trip overhead dominates over row-write cost; raise this "
            "(ARYX_LANDING_BATCH_SIZE) for Oracle deployments to amortize that overhead "
            "over more rows per call. Default of 500 preserves today's behavior "
            "everywhere this isn't explicitly raised."
        ),
    )
    embed_dim: int = Field(default=768, description="Expected embedding dim; startup check fails on mismatch.")
    chunk_size: int = Field(default=1000, description="Target chunk size in characters.")
    chunk_overlap: int = Field(default=100, description="Overlap in characters between adjacent chunks.")
    worker_threads: int = Field(default=4, description="Concurrent ingest workers (ThreadPoolExecutor).")
    max_block_size: int = Field(
        default=5000,
        description="Max records per blocking group in resolution. Groups over this size are logged and skipped.",
    )
    job_heartbeat_timeout_minutes: int = Field(
        default=10,
        description=(
            "Minutes of zero job-status updates before a job is presumed to have "
            "lost its worker and is marked failed (JobStore.sweep_stale_heartbeat, "
            "ARYX_JOB_HEARTBEAT_TIMEOUT_MINUTES). Deliberately much shorter than "
            "ARYX_JOB_TIMEOUT_MINUTES (default 120) -- that setting tolerates a "
            "legitimately long-running job; this one detects a crashed/restarted "
            "worker, which stops producing ANY update, usually within seconds. "
            "Safe to keep short only because the cpq XML raw-graph resolve path "
            "(and the chunked entity-resolution path it can route into) now emit "
            "periodic on_progress heartbeats through their previously-silent "
            "phases specifically so this check has something recent to compare "
            "against — see docs/ingestion/"
            "CPQ_XML_CONFIRM_RESOLVE_PERFORMANCE_ISSUES_2026-10-04.md §0."
        ),
    )
