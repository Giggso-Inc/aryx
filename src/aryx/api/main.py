"""Combined Aryx API: graph queries + admin/ingestion + MCP /mcp endpoint."""
from __future__ import annotations

import asyncio
import logging
import os

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

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
from aryx.api.doc_discover_api import doc_discover_router
from aryx.api.file_ingest_api import file_ingest_router, shutdown_executor
from aryx.api.graph_api import graph_router
from aryx.api.ingest_question_api import ingest_question_router
from aryx.api.jobs_api import jobs_router
from aryx.api.lab_api import lab_router
from aryx.api.mcp_tokens_api import mcp_tokens_router
from aryx.api.observability_api import observability_router
from aryx.api.ontology_api import ontology_router
from aryx.api.ontology_assist_api import ontology_assist_router
from aryx.api.relationship_type_api import relationship_type_router
from aryx.api.rest_ingest_api import rest_ingest_router
from aryx.api.rules_api import rules_router
from aryx.api.shay_bridge_api import shay_bridge_router
from aryx.api.share_config_api import share_config_router
from aryx.api.versions_api import versions_router
from aryx.api.workspace_api import workspace_router

# Attach a StreamHandler directly to the aryx logger so INFO output always
# reaches stdout regardless of whether uvicorn was started with --log-level.
# Without this, messages propagate to the root logger which uvicorn leaves at
# WARNING by default, silently dropping aryx INFO logs.
# propagate=False prevents double-printing when the caller ALSO configures root.
_log_level = getattr(logging, os.environ.get("ARYX_LOG_LEVEL", "INFO").upper(), logging.INFO)
_aryx_logger = logging.getLogger("aryx")
_aryx_logger.setLevel(_log_level)
if not _aryx_logger.handlers:
    _h = logging.StreamHandler()
    _h.setLevel(_log_level)
    _h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    _aryx_logger.addHandler(_h)
    _aryx_logger.propagate = False
logger = logging.getLogger(__name__)

# uvicorn's own access log ("INFO:     127.0.0.1:xxxxx - "GET /health ..."")
# has NO timestamp in its default formatter — every incident triage this
# session needed to correlate an access-log line against a timestamped app
# log line (health-check JSON, cpq_* lines) with no time on the access line
# itself, making it impossible to tell how long a request actually sat
# in-flight from the access log alone. uvicorn.access is a distinct logger
# with its own handler/formatter installed at uvicorn startup — reconfigure
# it here (module import time, so this always runs before the first request)
# rather than depending on a --log-config file being passed to the uvicorn
# CLI invocation in docker-compose.yml's `command:` line.
_access_logger = logging.getLogger("uvicorn.access")
for _h in _access_logger.handlers:
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))


class _RequestTimingMiddleware:
    """ASGI middleware: log a timestamped start/end line for every HTTP
    request, so a stuck request shows a "started, never finished" line
    instead of silence between whatever the request handler itself logs.
    Confirmed need (2026-08-14 incident): a POST /api/ask/threads/message
    took 15 min and a GET /api/graph took 5 min then 502'd, with nothing in
    aryx.cpq.engine/ask_api logs to show WHERE either request was stuck —
    only the access log line printed, and only after the fact, with no
    timestamp on it at all (see uvicorn.access fix above)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        import time

        method = scope.get("method", "?")
        path = scope.get("path", "?")
        query = scope.get("query_string", b"").decode("utf-8", "ignore")
        req_id = f"{time.monotonic_ns():x}"
        started = time.monotonic()
        logger.info(
            "request_start id=%s %s %s%s", req_id, method, path,
            f"?{query}" if query else "",
        )
        status_holder = {"code": None}

        async def _send(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message.get("status")
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception:
            elapsed = time.monotonic() - started
            logger.exception(
                "request_error id=%s %s %s elapsed_s=%.3f",
                req_id, method, path, elapsed,
            )
            raise
        else:
            elapsed = time.monotonic() - started
            logger.info(
                "request_end id=%s %s %s status=%s elapsed_s=%.3f",
                req_id, method, path, status_holder["code"], elapsed,
            )


def _authenticate_mcp(request):
    """Return the bearer principal, or ``None`` on missing/invalid auth."""
    from aryx.mcp.http_auth import authenticate_authorization_header

    return authenticate_authorization_header(
        request.headers.get("authorization") or ""
    )


def _bearer_ok(request) -> bool:
    """Compatibility wrapper returning whether MCP authentication succeeded."""
    return _authenticate_mcp(request) is not None


def _mount_mcp(app: FastAPI) -> None:
    """Mount the MCP SSE transport at /mcp with bearer-token auth."""
    try:
        from mcp.server.sse import SseServerTransport
        from starlette.routing import Mount, Route

        from aryx.mcp.auth import bind_principal, reset_principal
        from aryx.mcp.server import server

        sse = SseServerTransport("/mcp/messages/")

        async def handle_sse(request):
            principal = _authenticate_mcp(request)
            if principal is None:
                raise HTTPException(401, "missing or invalid bearer token")
            principal_token = bind_principal(principal)
            try:
                async with sse.connect_sse(
                    request.scope, request.receive, request._send,
                ) as streams:
                    await server.run(
                        streams[0],
                        streams[1],
                        server.create_initialization_options(),
                    )
            finally:
                reset_principal(principal_token)

        app.router.routes.append(Route("/mcp", endpoint=handle_sse))
        app.router.routes.append(Mount("/mcp/messages/",
                                       app=sse.handle_post_message))
        logger.info("MCP mounted at /mcp")
    except Exception as exc:  # noqa: BLE001
        logger.warning("MCP mount failed: %s", exc)


async def _stale_job_sweep() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            from aryx.config import get_settings
            from aryx.store.job_store import JobStore
            timeout_min = int(os.environ.get("ARYX_JOB_TIMEOUT_MINUTES", "120"))
            JobStore(get_settings().effective_dsn()).sweep_stale(timeout_min)
        except Exception as exc:  # noqa: BLE001
            logger.warning("stale-job sweep error: %s", exc)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    from aryx.config import get_settings
    from aryx.store.migrate import apply_migrations
    from aryx.api.file_ingest_api import shutdown_executor
    apply_migrations(get_settings().rdb_dsn)
    _task = asyncio.ensure_future(_stale_job_sweep())
    try:
        yield
    finally:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        shutdown_executor()
        from aryx.store.pool import close_all
        close_all()


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
