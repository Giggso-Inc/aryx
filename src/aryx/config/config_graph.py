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
