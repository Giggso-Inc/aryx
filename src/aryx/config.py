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
    graph_query_timeout: int = Field(
        default=30_000,
        description=(
            "Per-query timeout in milliseconds passed to every FalkorDB "
            "query via GraphReader._query(). FalkorDB's own built-in default "
            "is 5000ms — a real incident: GET /graph on workspace 44/45 "
            "intermittently returned 500 (redis.exceptions.ResponseError: "
            "Query timed out) because some relationship-traversal queries on "
            "large, heavily-linked workspaces legitimately take longer than "
            "5s even with REL.name indexed. Set to 0 to disable the override "
            "and fall back to FalkorDB's own default (passed as None, not a "
            "literal 0ms, which would fail every query instantly). "
            "Override with ARYX_GRAPH_QUERY_TIMEOUT."
        ),
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
    cooccurrence_link_enabled: bool = Field(
        default=True,
        description=(
            "Enable Tier-0 deterministic co-occurrence linking: connects "
            "entities extracted from the SAME document chunk (doc_id + "
            "chunk_index) via a weak, distinctly-named edge. A real "
            "incident: a 97-type PDF batch ended with 63% of its entities "
            "isolated even after FK detection, dimension linking, and the "
            "LLM safety net all ran — none of those signals exist for "
            "free text, but chunk co-occurrence does. Safe no-op for "
            "tabular/XML data (no chunk_index attribute exists there). "
            "Override with ARYX_COOCCURRENCE_LINK_ENABLED."
        ),
    )
    cooccurrence_max_pairs_per_chunk: int = Field(
        default=200,
        description=(
            "Max entity pairs linked per document chunk. Defense in depth "
            "against a pathological chunk with an unusually large mention "
            "count — pair count grows quadratically with mentions per "
            "chunk, though in practice a chunk maps to one passage of text "
            "and typically has only a handful of mentions. "
            "Override with ARYX_COOCCURRENCE_MAX_PAIRS_PER_CHUNK."
        ),
    )
    dimension_link_enabled: bool = Field(
        default=True,
        description=(
            "Enable Tier-2 deterministic dimension-hub linking: connects "
            "entities across types that share a low-cardinality dimension "
            "column (state, fiscal period, category code) with no row-level "
            "key, via a shared hub entity — a weaker, distinctly-named edge "
            "than a real FK. A real incident: a 300K-row table had no usable "
            "key and stayed 100% isolated even though its dimension columns "
            "had full value overlap with other ingested tables. "
            "Override with ARYX_DIMENSION_LINK_ENABLED."
        ),
    )
    dimension_min_distinct_values: int = Field(
        default=2,
        description=(
            "Minimum distinct values a column must have to be considered a "
            "dimension candidate (a constant column carries no linking "
            "information). Override with ARYX_DIMENSION_MIN_DISTINCT_VALUES."
        ),
    )
    dimension_max_cardinality_ratio: float = Field(
        default=0.05,
        description=(
            "Max distinct-values/total-rows ratio for a column to count as a "
            "dimension (the opposite profile of a usable FK key, which must "
            "be near-unique). A column above this ratio is treated as a "
            "candidate identifier, not a shared dimension, and left to "
            "dynamic_fk.py. Override with ARYX_DIMENSION_MAX_CARDINALITY_RATIO."
        ),
    )
    dimension_min_overlap: float = Field(
        default=0.3,
        description=(
            "Min value-overlap ratio (|intersection| / min(|A|,|B|)) for two "
            "dimension candidate columns from DIFFERENT types to be clustered "
            "into the same dimension group. Override with "
            "ARYX_DIMENSION_MIN_OVERLAP."
        ),
    )
    dimension_min_types: int = Field(
        default=2,
        description=(
            "Minimum distinct ontology types a dimension group must span "
            "before hub entities are materialized for it — a dimension only "
            "shared within one type provides no cross-type linking value. "
            "Override with ARYX_DIMENSION_MIN_TYPES."
        ),
    )
    dimension_max_edges_per_group: int = Field(
        default=2_000_000,
        description=(
            "Max hub edges detect_and_link_dimensions() will write for a "
            "single dimension group. Deliberately much larger than "
            "max_relationships_per_fk_spec: that cap defends against a "
            "dangerous O(entities x entities) cross-product from a bad FK "
            "join key. Dimension-hub linking is O(entities) — one edge per "
            "row to its hub, never a cross-product — so a large edge count "
            "here reflects a large, legitimately-connected dataset, not a "
            "runaway join. A real incident: reusing the FK-spec cap here "
            "truncated a real dimension link at 50,000 edges, leaving most "
            "of a 300K-row table still isolated even after a real, valid "
            "shared dimension was correctly found. "
            "Override with ARYX_DIMENSION_MAX_EDGES_PER_GROUP."
        ),
    )
    relate_isolated_max_anchors: int = Field(
        default=5,
        description=(
            "Max candidate anchor types _relate_isolated() tries per isolated "
            "type before giving up on it. Previously only ONE fixed anchor "
            "(the first other type in sample order) was ever tried — a real "
            "relationship to a DIFFERENT type was permanently missed whenever "
            "that single pairing came back unrelated. Bounded (not unbounded "
            "over every other type) to keep worst-case cost at "
            "O(isolated_types × max_anchors), not O(isolated_types × all_types). "
            "Override with ARYX_RELATE_ISOLATED_MAX_ANCHORS."
        ),
    )
    relate_isolated_max_samples_per_type: int = Field(
        default=3,
        description=(
            "Max isolated entities of the SAME type _relate_isolated() "
            "samples and tries per anchor, before giving up on that type. "
            "Previously only the FIRST isolated entity of a type was ever "
            "tried — for a type whose members vary a lot (a real incident: "
            "document-extracted list-style mentions of one type where "
            "different members are substantively unrelated topics despite "
            "sharing a type name), the single sampled member easily missed "
            "a real relationship a DIFFERENT member of the same type would "
            "have shown. Bounded together with relate_isolated_max_anchors "
            "at O(isolated_types × max_samples × max_anchors). "
            "Override with ARYX_RELATE_ISOLATED_MAX_SAMPLES_PER_TYPE."
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
    discovery_max_payload_mb: int = Field(
        default=512,
        description=(
            "Max size (MB), AFTER gzip compression, of a single document-"
            "discovery result written to aryx_discovery in one INSERT "
            "(migration 0036: gzip-compressed JSON in a BYTEA column). A "
            "multi-file tabular batch (e.g. dozens of BigMachines/Oracle "
            "CPQ CSV catalog exports) whose compressed size exceeds this "
            "is rejected with a clear error at the application layer "
            "instead of being attempted as one giant write -- confirmed "
            "live that an oversized single write can overrun Postgres's "
            "wire-protocol message-length framing and get the connection "
            "killed outright ('invalid message length'), not just run "
            "slowly. Earlier versions of this guard measured the RAW "
            "(uncompressed) JSONB size and were capped near Postgres's "
            "hard, non-configurable ~256MB limit on a single JSONB array's "
            "serialized size (confirmed live via psycopg.errors."
            "ProgramLimitExceeded on a 33-file batch) -- BYTEA has no such "
            "array-size restriction (TOASTed up to ~1GB), and compressing "
            "text-heavy CSV data before writing buys substantial headroom "
            "on top of that, hence the higher default here. Override with "
            "ARYX_DISCOVERY_MAX_PAYLOAD_MB."
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

    # ── Dynamic (value-based + LLM) FK detection ──────────────────────────────
    # Runs after the existing column-name passes (_detect_fk_links), over
    # whatever pairs those passes did NOT already resolve, so it never
    # duplicates or regresses the fast heuristics — only fills the gap they
    # can't see (differently-named columns, derived/semantic joins).
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
    cpq_shadow_intent_enabled: bool = Field(
        default=False,
        description=(
            "Phase 1, docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md: run the "
            "shadow-mode universal intent classifier (_shadow_classify_cpq_"
            "turn in ask_api.py) alongside the real deterministic dispatch "
            "on every CPQ turn, logging its classification for later "
            "comparison. Off by default: live-confirmed this added an extra "
            "unconditional LLM call to every single test invoking "
            "_run_cpq_turn, taking the CPQ/BML suite from ~10s to ~128s with "
            "zero behavioral change (the shadow call is try/except-wrapped "
            "and never affects a turn's real answer) -- purely a test-speed "
            "and CI-cost concern, same class of always-on-cost issue "
            "bml_use_llm above already guards against. Override with "
            "ARYX_CPQ_SHADOW_INTENT_ENABLED=true to collect real shadow-mode "
            "data against live traffic."
        ),
    )
    cpq_qa_ambiguity_check_enabled: bool = Field(
        default=False,
        description=(
            "Phase 3, docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md: before "
            "answering a generic graph Q&A question, classify whether the "
            "question is itself ambiguous (2+ plausible distinct meanings) "
            "and ask a clarifying question instead of committing to one "
            "interpretation. Off by default for the same test-speed/CI-cost "
            "reason as cpq_shadow_intent_enabled -- an unconditional extra "
            "LLM call on every Q&A turn. Override with "
            "ARYX_CPQ_QA_AMBIGUITY_CHECK_ENABLED=true."
        ),
    )
    cpq_llm_first_enabled: bool = Field(
        default=True,
        description=(
            "Phase 2 (PARTIAL), docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md: "
            "let the universal intent classifier dispatch directly to "
            "_handle_cascade/_handle_cascade_multi/_build_no_value_response "
            "(bypassing the regex detectors) for CHANGE_REQUEST/"
            "CHANGE_REQUESTS_MULTI/CHANGE_TARGET_WITHOUT_VALUE/AMBIGUOUS/"
            "OUT_OF_SCOPE only -- every other category still falls through "
            "to the unchanged deterministic path (see "
            "_dispatch_intent_result's docstring for the full category "
            "list this initial landing does not yet cover). On by default "
            "(2026-07-28) for local/dev testing of the LLM-first flow -- "
            "note this carries the same extra-LLM-call cost as "
            "cpq_shadow_intent_enabled on every STEP 6 turn, and has NOT "
            "been validated against real Phase 1 shadow-mode disagreement/"
            "resolution-failure data yet -- the plan doc's own Phase 2 "
            "criteria ('once shadow mode shows the deterministic "
            "resolution step reliably resolves what the LLM names') has "
            "not actually been met. Set ARYX_CPQ_LLM_FIRST_ENABLED=false "
            "to fall back to the pure deterministic path (e.g. for a fast "
            "CI run) or before considering this validated for production."
        ),
    )
    cpq_llm_first_universal_enabled: bool = Field(
        default=True,
        description=(
            "Phase 4 (docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md §8): "
            "runs the LLM-first dispatcher (_dispatch_intent_result, gated "
            "above by cpq_llm_first_enabled) on EVERY turn regardless of "
            "session.status -- previously it only ran inside the "
            "awaiting_approval/post_approval block, so it never fired "
            "during the actual configuring-stage conversation, which is "
            "most real traffic. Also enables the 6 new dispatch branches "
            "(PRODUCT_QUANTITY_CHANGE, COUNTRY_CHANGE, "
            "BULK_QUANTITY_CHANGE, RESPONSE_MODE_REQUEST, APPROVAL) that "
            "Phase 2's initial landing deliberately deferred. Off by "
            "default -- ships behind this flag for shadow/staging "
            "validation first, per the plan doc's own rollout discipline, "
            "since these are real mutating actions during active "
            "configuration, not just post-review edits. Requires "
            "cpq_llm_first_enabled=True to have any effect at all -- this "
            "flag only widens WHEN/WHAT that mechanism covers, it doesn't "
            "replace it. Override with "
            "ARYX_CPQ_LLM_FIRST_UNIVERSAL_ENABLED=true."
        ),
    )
    cpq_intent_gemini_model: str = Field(
        default="gemini-2.5-pro",
        description=(
            "Pinned model id for the CPQ intent gateway (cpq/intent_gateway.py). "
            "One structured call per turn; logged with session run_id. "
            "Override with ARYX_CPQ_INTENT_GEMINI_MODEL."
        ),
    )
    cpq_intent_mode: str = Field(
        default="llm_first",
        description=(
            "Top-level /ask intent router mode (Prompt 3). "
            "'llm_first' (default) — gateway classifies every cold-start "
            "turn; handlers only execute. Required for route_meta.quantity/"
            "route_meta.country (docs/CPQ_TURN1_COUNTRY_EXTRACTION_DEFECT_"
            "PLAN_2026_08_13.md) to ever reach the actual turn at all -- "
            "'shadow' strips both before the turn runs (observe-only), so "
            "a turn-1 message stating the country/quantity is left entirely "
            "to the deterministic regex extractor with no LLM fallback, "
            "even when the regex mis-parses it. "
            "'deterministic_first' — legacy is_cpq_question regex/alias gate "
            "(no gateway). "
            "'shadow' — deterministic path decides; gateway classifies in "
            "parallel for agreement logs only (grep by run_id). "
            "Rollback = set ARYX_CPQ_INTENT_MODE=shadow or "
            "=deterministic_first."
        ),
    )
    cpq_intent_timeout_s: float = Field(
        default=10.0,
        description=(
            "Hard timeout (seconds) for the top-level intent gateway call. "
            "On timeout/error, escape hatch falls back to the deterministic "
            "is_cpq_question path. Override with ARYX_CPQ_INTENT_TIMEOUT_S."
        ),
    )
    cpq_intent_classify_timeout_s: float = Field(
        default=120.0,
        description=(
            "Hard timeout (seconds) for classify_intent (intent_gateway.py) "
            "-- the mid-session LLM-first classifier, distinct from "
            "cpq_intent_timeout_s (the turn-1 top-level router's own "
            "timeout). Added docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md "
            "§8 Phase 4: classify_intent had no timeout wrapper at all "
            "before this, unlike classify_ask_route -- broadening how "
            "often it's called (every turn, not just post-approval) made "
            "an unbounded hang a bigger exposure than it was before. On "
            "timeout, returns action='fallback' -- callers already treat "
            "that as 'proceed to the deterministic path', so no new "
            "caller-side branch is needed. Override with "
            "ARYX_CPQ_INTENT_CLASSIFY_TIMEOUT_S."
        ),
    )
    bml_tier2_max_per_turn: int = Field(
        default=50,
        description=(
            "Amendment 18 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): hard "
            "ceiling on how many distinct scripts one CPQ turn's BmlEvaluator "
            "will attempt via Tier-2 LLM, across every pass of that turn's "
            "evaluate_rules_loop combined. Live-measured need: a single large "
            "catalog (900+ attrs) surfaced 823 distinct scripts needing "
            "Tier-2 in one turn before parallelization/Tier-1 idiom work — "
            "concurrency (BmlEvaluator.prefetch_tier2) and a smarter Tier-1 "
            "(evaluate_hide_master_list) both cut that dramatically, but "
            "this cap is the backstop for whatever's still left, or a "
            "different large catalog this session hasn't seen. Once "
            "reached, every FURTHER script this turn treats Tier-2 as "
            "unavailable and falls back to today's existing safe default "
            "(no constraint/hide decision derived — never a guess), exactly "
            "as if ARYX_BML_USE_LLM were off for just those extra scripts. "
            "Override with ARYX_BML_TIER2_MAX_PER_TURN."
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
    extract_mention_workers: int = Field(
        default=4,
        description=(
            "Parallel LLM calls within extract_mentions() for a single "
            "document's chunks. Extraction used to be one chunk at a time: a "
            "50-page PDF (~330 chunks) measured at 36 minutes wall-clock; a "
            "1000+ page document scales roughly linearly to many hours at "
            "that rate, which per_doc_timeout would abandon partway through "
            "(and, before incremental persistence, lost every mention "
            "extracted so far when that happened). Raise for a cloud LLM "
            "provider (Gemini/OpenAI/Anthropic) that handles concurrent "
            "requests; keep at 1-2 for a single local Ollama instance, where "
            "parallel requests just queue with no real throughput gain. "
            "Override with ARYX_EXTRACT_MENTION_WORKERS."
        ),
    )
    extract_mention_progress_flush_chunks: int = Field(
        default=20,
        description=(
            "How often (in completed chunks) extract_mentions() invokes its "
            "progress callback, which persists the mentions extracted so far "
            "and updates the job's live stage/pct. Without this, a "
            "per_doc_timeout expiry or crash partway through a long document "
            "lost every mention extracted up to that point, since the full "
            "record list was previously only returned at the very end of "
            "extraction. Override with "
            "ARYX_EXTRACT_MENTION_PROGRESS_FLUSH_CHUNKS."
        ),
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
    ontology_export_max_entities: int = Field(
        default=50_000,
        description=(
            "Max entity count in a workspace above which GET /ontology/export "
            "rejects with 413 instead of running the synchronous export. "
            "Serialising a very large workspace can run long enough for a "
            "reverse proxy's read timeout to kill the connection first, "
            "which the client sees as a bare 502 Bad Gateway with no useful "
            "detail. Set to 0 to disable the cap. "
            "Override with ARYX_ONTOLOGY_EXPORT_MAX_ENTITIES."
        ),
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
