"""FastAPI read API over the FalkorDB knowledge graph (Increment 6)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel

from aryx import explore
from aryx.config import get_settings
from aryx.cpq.engine import CpqEngine
from aryx.graph import GraphReader
from aryx.graph.feature_search import search_by_feature, search_products_combined
from aryx.ports import ports
from aryx.raven_log import new_span_id, new_trace_id, raven_log
from aryx.store.entity_store import EntityStore

# Stateless -- mirrors ask_api.py's own module-level singleton (CpqEngine
# takes no constructor args; all state is passed explicitly per call).
_cpq_engine = CpqEngine()


class EntitySearchRequest(BaseModel):
    """Body for POST /entities/search -- Phase 1 (graph) + Phase 2 (Postgres
    Data Table) feature/region search, plus the merge between them
    (2026-09-15/16 andie analysis). A JSON body avoids the query-string
    encoding edge cases a repeated ?attr= param would hit for multi-word
    attribute values (e.g. "Base Model").

    Three effective modes, chosen by which fields are set:
    - Neither `region` nor (`feature_label` + `feature_value`) given: graph
      search only (find_entities(attrs=...), or search_by_feature() when
      with_hiding_rules=True) -- unchanged from Phase 1 alone.
    - `region` and/or (`feature_label` + `feature_value`) given, with no
      `ontology_type`/`name`/`attrs`: Postgres Data Table search only,
      cross-referenced against the graph by name where a match exists.
    - Both sides given: the full merge, one entry per model with `source`
      indicating which side(s) matched.

    with_hiding_rules=False (default) is equivalent to find_entities(attrs=...)
    alone -- cheap, no CpqEngine/Postgres round-trip. Set True to additionally
    annotate each graph candidate with hidden_by_rule/hiding_rule_names.
    Ignored once a Postgres-side filter is set, since search_products_
    combined() always attaches graph context to Data-Table-only matches
    that exist in the graph -- there's no cheaper graph-less variant of
    that path.
    """

    ontology_type: str | None = None
    name: str | None = None
    attrs: dict[str, str] | None = None
    filled: dict[str, str] | None = None
    limit: int = 50
    with_hiding_rules: bool = False

    # Phase 2 / merge fields -- see Phase2_DataTable_Schema_Audit.md.
    region: str | None = None
    feature_label: str | None = None
    feature_value: str | None = None
    cpq_model: str | None = None
    catalog_prefix: str = ""


def _reader(workspace_id: int = 1) -> GraphReader:
    # Default workspace 1 = "Default". Callers pass ?workspace_id= to select
    # a different workspace.  Multi-tenant deployments should derive this from
    # the auth context instead of relying on the query-param default.
    return ports().graph_reader(workspace_id)  # type: ignore[return-value]


def _overview_payload(workspace_id: int) -> dict[str, Any]:
    """Build the brief-driven graph overview from the relational truth."""
    store = EntityStore(get_settings().effective_dsn(), workspace_id)
    try:
        entities, relationships, brief = store.overview_inputs()
        return explore.domain_overview_view(
            entities,
            relationships,
            brief,
        )
    finally:
        store.close()


def graph_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        # Sample raven-log instrumentation (HTTP path + P4 info).
        raven_log(
            level="INFO",
            criticality="P4",
            message="health check ok",
            error_code="",
            trace_id=new_trace_id(),
            span_id=new_span_id(),
            context={"path": "/health"},
        )
        return {"status": "ok"}

    @router.get("/entities")
    def find_entities(
        type: str | None = None, name: str | None = None, limit: int = 50,
        reader: GraphReader = Depends(_reader),
    ) -> list[dict[str, Any]]:
        return reader.find_entities(ontology_type=type, name=name, limit=limit)

    @router.post("/entities/search")
    def search_entities(
        body: EntitySearchRequest, workspace_id: int = 1,
        reader: GraphReader = Depends(_reader),
    ) -> list[dict[str, Any]]:
        """Attribute-aware entity search -- Phase 1 of feature/region search.

        Lets a caller search by attribute value (e.g. {"Region": "US"} or
        {"Feature Type": "Encryption"}) instead of only by exact ontology_type
        or name (Phase 1), by a Data Table region/feature constraint that
        never reaches FalkorDB (Phase 2), or both merged in one call -- see
        EntitySearchRequest's own docstring for which fields select which
        mode.
        """
        if body.region or (body.feature_label and body.feature_value):
            return search_products_combined(
                reader, _cpq_engine, workspace_id,
                region=body.region, feature_label=body.feature_label,
                feature_value=body.feature_value, ontology_type=body.ontology_type,
                name=body.name, attrs=body.attrs, cpq_model=body.cpq_model,
                filled=body.filled, limit=body.limit, catalog_prefix=body.catalog_prefix,
            )
        if body.with_hiding_rules:
            return search_by_feature(
                reader, _cpq_engine, workspace_id,
                ontology_type=body.ontology_type, name=body.name,
                attrs=body.attrs, filled=body.filled, limit=body.limit,
            )
        return reader.find_entities(
            ontology_type=body.ontology_type, name=body.name,
            attrs=body.attrs, limit=body.limit,
        )

    @router.get("/graph")
    def full_graph(
        rel_limit: int = 2000,
        reader: GraphReader = Depends(_reader),
    ) -> dict[str, Any]:
        """Connected subgraph for graph canvas rendering.

        Returns up to *rel_limit* relationships and the entities at their
        endpoints.  Every returned entity has at least one edge, so the
        graph-canvas layout algorithm produces a proper connected diagram
        instead of a linear list of orphan nodes.
        """
        return reader.subgraph(rel_limit=rel_limit)

    @router.get("/graph/overview")
    def graph_overview(workspace_id: int = 1) -> dict[str, Any]:
        """Brief-driven overview graph plus domain highlight metadata."""
        return _overview_payload(workspace_id)

    @router.post("/graph/cypher")
    def cypher_read(body: dict[str, Any]) -> dict[str, Any]:
        """Run a read-only Cypher query via FalkorDB's server-enforced
        read-only mode (GRAPH.RO_QUERY), not just an app-side keyword
        blacklist -- the database itself rejects any write operation,
        including write-capable procedure calls a regex can't catch.

        Found by post-merge review: this previously called store.run(),
        a method that never existed on FalkorStore -- every call crashed
        with AttributeError regardless of the keyword check below.
        """
        import re as _re
        q = str(body.get("query") or "")
        if _re.search(r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DROP|DETACH|CALL)\b",
                      q, _re.IGNORECASE):
            raise HTTPException(400, "read-only — write keywords rejected")
        wid = int(body.get("workspace_id", 1))
        from aryx.graph.falkor_store import FalkorStore
        from aryx.workspaces import ws_graph
        store = FalkorStore(get_settings().graph_url, ws_graph(wid))
        try:
            rows = store.run_read_only(q, params={})
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"cypher failed: {exc}") from exc
        return {"rows": rows[: int(body.get("limit", 50))]}

    @router.get("/entities/{entity_id}")
    def get_entity(
        entity_id: int, reader: GraphReader = Depends(_reader)
    ) -> dict[str, Any]:
        entity = reader.get_entity(entity_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="entity not found")
        return entity

    @router.get("/entities/{entity_id}/neighbors")
    def neighbors(
        entity_id: int, reader: GraphReader = Depends(_reader)
    ) -> list[dict[str, Any]]:
        return reader.neighbors(entity_id)

    @router.get("/entities/{entity_id}/provenance")
    def provenance(
        entity_id: int, reader: GraphReader = Depends(_reader)
    ) -> list[dict[str, Any]]:
        return reader.provenance(entity_id)

    @router.get("/entities/{entity_id}/path/{target_id}")
    def path(
        entity_id: int, target_id: int, max_hops: int = 6,
        reader: GraphReader = Depends(_reader),
    ) -> list[dict[str, Any]]:
        return reader.shortest_path(entity_id, target_id, max_hops)

    return router


def create_app() -> FastAPI:
    app = FastAPI(title="Aryx Graph API", version="1.0")
    app.include_router(graph_router())
    return app


app = create_app()
