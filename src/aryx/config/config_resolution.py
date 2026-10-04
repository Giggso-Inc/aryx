"""Entity-resolution + embedding settings — a Settings mixin.

Split out of `config.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See `config_core.py`'s docstring for the mixin-composition
rationale.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class ResolutionSettingsMixin(BaseSettings):
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
    er_chunk_threshold: int = Field(
        default=100_000,
        description=(
            "Record count above which resolve_run() dispatches to the "
            "streaming block-wise resolver (aryx.resolution.chunked."
            "resolve_chunked, backed by Postgres — resumable, bounded memory) "
            "instead of the in-memory resolve(). Below this threshold the "
            "in-memory path stays the fast path — chunking adds Postgres "
            "round-trips that aren't worth it for small runs. "
            "A large tabular sheet with no natural row cap (e.g. a 300K-row "
            "CSV/XLSX Data tab) previously ran the in-memory O(block-size²) "
            "blocking/scoring pass unconditionally and could stall ingestion "
            "for hours; this threshold is what activates the bounded, "
            "already-implemented alternative. Override with "
            "ARYX_ER_CHUNK_THRESHOLD. Ignored when exact_ids matching applies "
            "(id-keyed sources resolve by exact equality regardless of size, "
            "so chunking has nothing to add there)."
        ),
    )
    er_min_key_selectivity: float = Field(
        default=0.01,
        description=(
            "Min distinct-value ratio (0-1) the match-key text must clear "
            "before resolution runs its blocking/scoring pass at all. Below "
            "this, the key has too little identity signal to produce a "
            "meaningful block (e.g. a table whose match-key columns are "
            "each a single constant value across every row) — blocking "
            "still collapses everything into one oversized block that gets "
            "skipped, but only after paying the full cost of the key/"
            "blocking pass to discover that. Below the threshold, resolution "
            "is skipped entirely and one entity is materialized per record "
            "directly — same eventual outcome, none of the wasted work. "
            "Every skip is logged with the measured ratio and the match key "
            "involved, so a genuinely bad key choice stays visible and "
            "fixable. Ignored when exact_ids matching applies. Override "
            "with ARYX_ER_MIN_KEY_SELECTIVITY."
        ),
    )
    er_force_exact_min_selectivity: float = Field(
        default=0.99,
        description=(
            "Min sampled distinct-value ratio (0-1) required before a caller's "
            "force_exact=True request (resolve_run()) is actually honored. "
            "force_exact exists for match keys whose NAME doesn't look ID-like "
            "(so they'd never qualify for exact_ids the normal way) but whose "
            "VALUES the caller believes are unique -- e.g. cpq_ingestion's "
            "generic 'text' fallback key. A caller's belief alone is not "
            "proof: source=='default' in infer_match_keys_for_tag means no "
            "heuristic or LLM named the key, which says nothing about "
            "uniqueness, and forcing exact mode on a non-unique key would "
            "merge every record sharing a value into one entity (correctness "
            "regression, not a performance one). This threshold requires "
            "_key_selectivity() to independently confirm near-total "
            "uniqueness before force_exact is allowed to skip fuzzy scoring. "
            "Override with ARYX_ER_FORCE_EXACT_MIN_SELECTIVITY."
        ),
    )
    er_key_selectivity_sample_size: int = Field(
        default=2000,
        description=(
            "Max records sampled to measure match-key selectivity (see "
            "er_min_key_selectivity) before deciding whether to run "
            "resolution at all. Bounds the cost of the check itself "
            "regardless of table size. Override with "
            "ARYX_ER_KEY_SELECTIVITY_SAMPLE_SIZE."
        ),
    )
    er_max_edges_per_run: int = Field(
        default=2_000_000,
        description=(
            "Max match edges the chunked resolver's cluster pass will "
            "consume for a single run. A real incident: a 308,104-record "
            "run whose columns were mostly low-cardinality produced "
            "14,374,847 match edges from scoring (46x the record count) — "
            "materializing that many edges plus the same-size pair_scores "
            "dict was enough memory pressure to crash the container mid-run, "
            "silently orphaning the job with no logged error. Edges beyond "
            "this cap are not consumed — logged clearly as a warning, never "
            "silent — so those specific pairs simply don't merge (safe "
            "degradation: under-clustering, not data loss) instead of risking "
            "another unbounded-memory crash. Override with "
            "ARYX_ER_MAX_EDGES_PER_RUN."
        ),
    )
    er_embed_workers: int = Field(
        default=8,
        description=(
            "Concurrent block-embedding calls (ThreadPoolExecutor) during "
            "entity resolution (docs/ingestion/SPARK_PARALLEL_MIGRATION_"
            "ANALYSIS_2026-09-23.md Phase 3). Live-measured: embedding is "
            "~99% of resolve()'s wall-clock time on a realistic dataset "
            "(scoring, routing, and union-find bookkeeping are comparatively "
            "free) -- but the routing/union-find loop itself must stay "
            "sequential (MultiKeyBlocker deliberately places each record in "
            "up to 3 overlapping blocks, and UnionFind/pair_scores/"
            "band_counts have no synchronization), so only the independent, "
            "side-effect-free embedding calls are parallelized, prefetched "
            "before that sequential loop runs. Override with "
            "ARYX_ER_EMBED_WORKERS."
        ),
    )
    embed_batch_size: int = Field(
        default=50,
        description=(
            "Texts per embedding HTTP call — used both by entity resolution "
            "and by document-ingestion chunk embedding. Keeps each call's "
            "duration roughly constant regardless of how many chunks/records "
            "a document or batch has, so it stays comfortably inside "
            "embed_http_timeout."
        ),
    )
    embed_http_timeout: float = Field(
        default=60.0,
        description=(
            "Per-call HTTP timeout in seconds for the local Ollama /api/embed "
            "request. Override with ARYX_EMBED_HTTP_TIMEOUT if embed_batch_size "
            "is raised and needs a longer allowance."
        ),
    )
