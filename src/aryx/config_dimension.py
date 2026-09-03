"""Co-occurrence + dimension-hub linking settings — a Settings mixin.

Split out of `config.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See `config_core.py`'s docstring for the mixin-composition
rationale.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class DimensionSettingsMixin(BaseSettings):
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
