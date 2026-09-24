"""Graph-projection settings — a Settings mixin.

Split out of `config.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See `config_core.py`'s docstring for the mixin-composition
rationale.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class GraphSettingsMixin(BaseSettings):
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
    oracle_graph_batch_workers: int = Field(
        default=4,
        description=(
            "Concurrent Oracle round-trips (ThreadPoolExecutor) for "
            "OracleGraphStore.add_entities_batch/add_relationships_batch "
            "during a full graph rebuild (docs/ingestion/SPARK_PARALLEL_"
            "MIGRATION_ANALYSIS_2026-09-23.md Phase 4 Part B). Each chunk "
            "targets a disjoint set of entity ids / edges, so chunks are "
            "independent -- unlike add_provenance_batch, which has an "
            "internal merge-sources -> select-ids -> merge-links dependency "
            "and stays sequential. A live measurement against this "
            "environment's Oracle ADB tier found a mixed result at "
            "workers=4 -- entities 68.0s (sequential) -> 74.7s (a "
            "regression), relationships roughly flat (25.7s -> 24.0s, "
            "1.07x) -- but the default is kept at 4 rather than dropped to "
            "1, since a single measurement on one ADB tier isn't reason "
            "enough to disable the mechanism outright; re-measure on the "
            "target deployment's actual ADB tier before trusting either "
            "direction. Set ARYX_ORACLE_GRAPH_BATCH_WORKERS=1 to disable. "
            "Not used for FalkorDB: that client has no connection pool of "
            "its own (a separate, pre-existing gap) and FalkorDB's "
            "single-threaded-per-shard command execution means client-side "
            "concurrency wouldn't translate to server-side parallel "
            "execution the way it was hoped to for Oracle."
        ),
    )
