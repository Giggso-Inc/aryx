"""Extraction/tabular-ingest settings — a Settings mixin.

Split out of `config.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See `config_core.py`'s docstring for the mixin-composition
rationale.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class IngestSettingsMixin(BaseSettings):
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
    discovery_max_payload_mb: int = Field(
        default=512,
        description=(
            "Max size (MB), AFTER gzip compression, of a single document-"
            "discovery result written to aryx_discovery's data_json column "
            "in one INSERT/UPDATE (DiscoveryStore._serialize_data: gzip then "
            "base64-encoded so the value stays a plain JSON string -- no "
            "BYTEA column or migration needed, works unchanged on both "
            "Postgres and Oracle ADB 26ai). A multi-file tabular batch "
            "(e.g. dozens of BigMachines/Oracle CPQ CSV catalog exports) "
            "whose compressed size exceeds this is rejected with a clear "
            "error at the application layer instead of being attempted as "
            "one giant write -- confirmed live that an oversized single "
            "write can overrun Postgres's wire-protocol message-length "
            "framing and get the connection killed outright ('invalid "
            "message length'), not just run slowly. Earlier versions of "
            "this guard measured the RAW (uncompressed) JSON size and were "
            "capped near Postgres's hard, non-configurable ~256MB limit on "
            "a single JSONB array's serialized size (confirmed live via "
            "psycopg.errors.ProgramLimitExceeded on a 33-file batch) -- "
            "compressing text-heavy CSV data before writing buys "
            "substantial headroom on top of that, hence the higher default "
            "here. Override with ARYX_DISCOVERY_MAX_PAYLOAD_MB."
        ),
    )
    cpq_rule_trace_dir: str = Field(
        default="var/cpq_rule_traces",
        description=(
            "Local directory for per-configuration-session rule-execution "
            "trace .jsonl files (docs/CPQ_RULE_EXPORT_AND_TRACE_TDD_PLAN.md). "
            "One file per session, keyed '{catalog_prefix}_{session_start_ts}."
            "jsonl', opened on first rule-fire and sealed on confirm. The "
            "same events are also written durably to Postgres (migration "
            "0037_rule_trace.sql) -- this directory is a convenience mirror, "
            "not the sole copy. Override with ARYX_CPQ_RULE_TRACE_DIR."
        ),
    )
    cpq_rule_trace_orphan_timeout_hours: int = Field(
        default=24,
        description=(
            "Hours an open rule-trace session may sit without reaching "
            "confirm (session.complete=True) before the sweep seals it as "
            "'orphaned_timeout' rather than leaving it open indefinitely. "
            "Override with ARYX_CPQ_RULE_TRACE_ORPHAN_TIMEOUT_HOURS."
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
