"""Dynamic (value-based + LLM) FK detection settings — a Settings mixin.

Runs after the existing column-name passes (_detect_fk_links), over
whatever pairs those passes did NOT already resolve, so it never
duplicates or regresses the fast heuristics — only fills the gap they
can't see (differently-named columns, derived/semantic joins).

Split out of `config.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See `config_core.py`'s docstring for the mixin-composition
rationale.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class FkDetectionSettingsMixin(BaseSettings):
    fk_dynamic_detection_enabled: bool = Field(
        default=True,
        description=(
            "Enable Stage 1 (value-overlap sampling) + Stage 2 (LLM judge) "
            "dynamic FK detection for tabular ingestion, covering pairs the "
            "column-name passes in _detect_fk_links miss entirely. "
            "Override with ARYX_FK_DYNAMIC_DETECTION_ENABLED=false."
        ),
    )
    fk_value_sample_size: int = Field(
        default=200,
        description=(
            "Max distinct (deduplicated) values sampled per column for Stage 1 "
            "value-overlap scoring. Sampling distinct values, not raw rows, "
            "keeps this cheap even for sources with heavy row duplication. "
            "Override with ARYX_FK_VALUE_SAMPLE_SIZE."
        ),
    )
    fk_value_overlap_threshold: float = Field(
        default=0.05,
        description=(
            "Min shared-normalized-value overlap ratio (0-1) for a column pair "
            "to become a Stage 2 LLM-judge candidate. Deliberately low: this is "
            "only a cheap pre-filter, not the final relationship decision — the "
            "LLM makes the real call, with a reason, on every pair that clears "
            "this bar. Override with ARYX_FK_VALUE_OVERLAP_THRESHOLD."
        ),
    )
    fk_dynamic_judge_workers: int = Field(
        default=4,
        description=(
            "Concurrent LLM-judge calls for Stage 2 candidate pairs "
            "(ThreadPoolExecutor). This bounds THROUGHPUT only — every "
            "candidate pair that clears Stage 1 is judged; none are dropped "
            "or capped by count, only processed with bounded concurrency so a "
            "large batch stays fast without ever silently skipping a pair. "
            "Override with ARYX_FK_DYNAMIC_JUDGE_WORKERS."
        ),
    )
    fk_prefix_transform_lengths: str = Field(
        default="2,3,4",
        description=(
            "Comma-separated prefix lengths tried as a fallback when a "
            "column pair's raw values don't overlap enough — catches "
            "DERIVED relationships like a truncated/grouped code (e.g. a "
            "2-digit category derived from a longer code's first 2 "
            "characters), which no naming convention or raw value match can "
            "find. Generic by design: no column name or specific transform "
            "is hardcoded, only a small set of lengths tried on both sides. "
            "Still LLM-judged and fanout-guarded like any other candidate — "
            "this only widens what reaches Stage 1's candidate list. Empty "
            "string disables prefix-transform matching entirely. Override "
            "with ARYX_FK_PREFIX_TRANSFORM_LENGTHS."
        ),
    )
    fk_key_suffixes: str = Field(
        default="_code,_id,_key,_num,_ref,_no,_cage",
        description=(
            "Comma-separated column-name suffixes treated as generic "
            "key/code indicators by the column-name FK passes (e.g. "
            "'sales_order_ref' ends with '_ref'). Domain-agnostic — these "
            "are structural naming conventions, not references to any "
            "specific dataset's columns. Override with ARYX_FK_KEY_SUFFIXES."
        ),
    )
    id_like_column_names: str = Field(
        default="id,uuid,guid,key",
        description=(
            "Comma-separated column names (case-insensitive, exact match) "
            "treated as a generic opaque-identifier signal — used both by "
            "the column-name FK passes (picking a join target column) and "
            "by entity resolution (deciding whether a source's match keys "
            "are all identifier-like, triggering exact-equality matching "
            "instead of fuzzy scoring). Override with "
            "ARYX_ID_LIKE_COLUMN_NAMES."
        ),
    )
    name_like_column_names: str = Field(
        default="name,full_name,title",
        description=(
            "Comma-separated column names (case-insensitive, exact match) "
            "treated as a generic display-name signal by the column-name FK "
            "passes when no id-like column is available as a join target. "
            "Override with ARYX_NAME_LIKE_COLUMN_NAMES."
        ),
    )
    fk_fanout_scan_rows: int = Field(
        default=20000,
        description=(
            "Max rows scanned per side when estimating a candidate FK pair's "
            "join fan-out (sum of matching-value-count products). Bounds the "
            "cost of the estimate regardless of table size — a capped partial "
            "scan is still a valid conservative signal. "
            "Override with ARYX_FK_FANOUT_SCAN_ROWS."
        ),
    )
    fk_max_estimated_fanout: int = Field(
        default=5000,
        description=(
            "Max estimated join fan-out (approximate relationship-row count) "
            "a candidate FK pair may produce before it is rejected as too "
            "low-selectivity to be a safe join key (e.g. a shared category/"
            "group code rather than a real identifier) — rejected candidates "
            "never reach the Stage 2 LLM judge and never become an fk_link. "
            "Found via a real incident: a shared low-cardinality 'Matl Group' "
            "column the LLM correctly judged as 'the same kind of value' "
            "produced 1.5M+ relationship rows from one spec, stalling "
            "ingestion for hours. Override with ARYX_FK_MAX_ESTIMATED_FANOUT."
        ),
    )
    max_relationships_per_fk_spec: int = Field(
        default=50000,
        description=(
            "Hard cap on relationships written by link_by_attribute() for a "
            "single FK spec — defense in depth alongside fk_max_estimated_"
            "fanout, so ANY spec (column-name-detected or dynamic-detected) "
            "that slips through with a non-selective join key logs a clear "
            "warning and stops instead of silently writing millions of rows "
            "and stalling the ingest job for hours. "
            "Override with ARYX_MAX_RELATIONSHIPS_PER_FK_SPEC."
        ),
    )
