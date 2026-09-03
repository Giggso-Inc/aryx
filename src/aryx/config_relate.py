"""Relate-stage settings — a Settings mixin.

Split out of `config.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See `config_core.py`'s docstring for the mixin-composition
rationale.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class RelateSettingsMixin(BaseSettings):
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
