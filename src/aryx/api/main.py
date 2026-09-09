"""Combined Aryx API: graph queries + admin/ingestion + MCP /mcp endpoint.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`main_logging.py` (aryx/uvicorn.access logger setup, run at import time),
`main_middleware.py` (`_RequestTimingMiddleware`), `main_mcp.py` (MCP
bearer auth + SSE mount), and `main_lifespan.py` (startup migrations +
stale-job sweep + shutdown), all re-imported here. Zero whitebox test
patches exist anywhere against `aryx.api.main.*` (confirmed via grep;
`test_mcp_sse_mount.py` imports `_mount_mcp` by bare name only), so the
split was purely mechanical. `create_app` — wiring every router together —
stays here.
"""
from __future__ import annotations

from fastapi import FastAPI

from aryx.api import main_logging  # noqa: F401 — runs logger setup at import time
from aryx.api.actions_api import actions_router
from aryx.api.adjudication_api import adjudication_router
from aryx.api.admin_api import admin_router
from aryx.api.ask_api import ask_router
from aryx.api.ask_thread_api import ask_thread_router
from aryx.api.brief_api import brief_router
from aryx.api.axioms_api import axioms_router, shapes_router
from aryx.api.ask_history_api import ask_history_router
from aryx.api.connect_api import connect_router
from aryx.api.data_api import data_router
from aryx.api.datasource_api import datasource_router
from aryx.api.demo_ingest_api import demo_ingest_router
from aryx.api.doc_discover.doc_discover_api import doc_discover_router
from aryx.api.file_ingest.file_ingest_api import file_ingest_router, shutdown_executor
from aryx.api.graph_api import graph_router
from aryx.api.ingest_question_api import ingest_question_router
from aryx.api.jobs_api import jobs_router
from aryx.api.lab_api import lab_router
from aryx.api.main_lifespan import _lifespan
from aryx.api.main_mcp import _authenticate_mcp, _bearer_ok, _mount_mcp
from aryx.api.main_middleware import _RequestTimingMiddleware
from aryx.api.mcp_tokens_api import mcp_tokens_router
from aryx.api.observability_api import observability_router
from aryx.api.ontology_api import ontology_router
from aryx.api.ontology_assist_api import ontology_assist_router
from aryx.api.relationship_type_api import relationship_type_router
from aryx.api.rest_ingest.rest_ingest_api import rest_ingest_router
from aryx.api.rules_api import rules_router
from aryx.api.shay_bridge_api import shay_bridge_router
from aryx.api.share_config_api import share_config_router
from aryx.api.versions_api import versions_router
from aryx.api.workspace_api import workspace_router

__all__ = [
    "_authenticate_mcp",
    "_bearer_ok",
    "_mount_mcp",
    "_RequestTimingMiddleware",
    "app",
    "create_app",
]


def create_app() -> FastAPI:
    """Build the Aryx FastAPI app with every router + MCP mounted."""
    from aryx.api.security import ApiKeyMiddleware
    app = FastAPI(title="Aryx API", version="1.0", lifespan=_lifespan)
    app.add_middleware(ApiKeyMiddleware)
    app.add_middleware(_RequestTimingMiddleware)
    app.include_router(graph_router())
    app.include_router(admin_router())
    app.include_router(ask_router())
    app.include_router(ask_thread_router())
    app.include_router(lab_router())
    app.include_router(data_router())
    app.include_router(ask_history_router())
    app.include_router(jobs_router())
    app.include_router(file_ingest_router())
    app.include_router(connect_router())
    app.include_router(demo_ingest_router())
    app.include_router(doc_discover_router())
    app.include_router(workspace_router())
    app.include_router(brief_router())
    app.include_router(datasource_router())
    app.include_router(ingest_question_router())
    app.include_router(relationship_type_router())
    app.include_router(ontology_assist_router())
    app.include_router(observability_router())
    app.include_router(ontology_router())
    app.include_router(axioms_router())
    app.include_router(shapes_router())
    app.include_router(rules_router())
    app.include_router(shay_bridge_router())
    app.include_router(share_config_router())
    app.include_router(rest_ingest_router())
    app.include_router(versions_router())
    app.include_router(mcp_tokens_router())
    app.include_router(adjudication_router())
    app.include_router(actions_router())
    _mount_mcp(app)
    return app


app = create_app()
