"""MCP bearer auth + SSE transport mount for the combined Aryx API app.

Split out of `api/main.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). `_mount_mcp` is directly imported (bare name, not patched)
by `tests/test_mcp_sse_mount.py` — confirmed via grep.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException

if TYPE_CHECKING:
    from aryx.mcp.http_auth import McpPrincipal

logger = logging.getLogger(__name__)


def _authenticate_mcp(request) -> "McpPrincipal | None":
    """Return the bearer principal, or ``None`` on missing/invalid auth."""
    from aryx.mcp.http_auth import authenticate_authorization_header

    return authenticate_authorization_header(
        request.headers.get("authorization") or ""
    )


def _bearer_ok(request) -> bool:
    """Compatibility wrapper returning whether MCP authentication succeeded."""
    return _authenticate_mcp(request) is not None


def _mount_mcp(app: FastAPI) -> None:
    """Mount the MCP Streamable HTTP transport at /mcp with bearer-token
    auth, in stateless mode.

    2026-09-11 (ported from dev-rv-msi's 1b269664): was
    mcp.server.sse.SseServerTransport. That transport splits every tool
    call into two separate HTTP requests -- a long-lived GET /mcp (opens
    the SSE stream, registers session_id in an in-process dict) and a
    following POST /mcp/messages/?session_id=... (the actual request,
    looked up against that same dict). Under multiple uvicorn workers
    sharing one listening socket via SO_REUSEPORT, the kernel -- not this
    app -- decides which worker accepts each connection: the GET and its
    immediately-following POST could land on DIFFERENT workers, and the
    POST's worker would never have registered that session_id, 404ing
    instantly ("Could not find session for ID"). This could not be fixed
    by sharing the registry the way _TABLES_CACHE was (Redis-backed) --
    that fix worked because the cached value was plain, serializable
    data; here the value is a LIVE anyio stream object bound to one
    worker's event loop, which cannot be handed to a different process
    via Redis or any other shared store.

    StreamableHTTPSessionManager(stateless=True) fixes this at the root:
    every request is a single, self-contained POST with no session_id to
    register or look up across requests at all -- there is nothing for a
    different worker to have missed. Verified (independently, against
    this checkout's own aryx.mcp package) that nothing here relies on
    server-initiated push/notification behavior (grepped for
    send_notification/progress_notification/create_message/elicit/
    session.send -- zero matches; server.py only uses
    @server.list_tools() and @server.call_tool(), pure request/response),
    which is the one thing stateless mode gives up.
    """
    try:
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.requests import Request
        from starlette.routing import Route

        from aryx.asgi_utils import RawAsgiEndpoint
        from aryx.mcp.auth import bind_principal, reset_principal
        from aryx.mcp.server import server

        session_manager = StreamableHTTPSessionManager(app=server, stateless=True)
        # _lifespan (main_lifespan.py) enters session_manager.run() around
        # app startup -- stashed on app.state since _mount_mcp runs after
        # FastAPI(lifespan=...) has already been constructed, but before
        # the app actually starts serving, so _lifespan sees this by the
        # time it's invoked.
        app.state.mcp_session_manager = session_manager

        async def handle_mcp(scope, receive, send) -> None:
            """Raw ASGI handler for /mcp -- must reach Starlette as an
            already-ASGI callable (via RawAsgiEndpoint), not a plain
            function/method endpoint, for the same reason the old SSE
            handler did: this sends its response directly through the
            raw ASGI `send` and never returns one, which a plain
            function/method endpoint's request_response() wrapping would
            crash on (live-confirmed 2026-08-31 for the SSE handler this
            replaces)."""
            request = Request(scope, receive=receive, send=send)
            principal = _authenticate_mcp(request)
            if principal is None:
                raise HTTPException(401, "missing or invalid bearer token")
            principal_token = bind_principal(principal)
            try:
                await session_manager.handle_request(scope, receive, send)
            finally:
                reset_principal(principal_token)

        app.router.routes.append(
            # methods=["GET"] required explicitly -- Route only defaults
            # this to ["GET"] for plain function/method endpoints
            # (Route.__init__'s inspect.isfunction/ismethod branch);
            # RawAsgiEndpoint is a class instance, so without this,
            # methods stays None and every HTTP method matches (Route.
            # matches()'s `if self.methods and ...` is falsy for None) --
            # caught in review of PR #289. POST carries every real
            # request in stateless mode; GET/DELETE are accepted too
            # since StreamableHTTPSessionManager.handle_request dispatches
            # on method internally and the mcp client library may probe
            # either.
            Route("/mcp", endpoint=RawAsgiEndpoint(handle_mcp),
                  methods=["GET", "POST", "DELETE"]),
        )
        logger.info("MCP mounted at /mcp (streamable-http, stateless)")
    except Exception as exc:  # noqa: BLE001
        logger.warning("MCP mount failed: %s", exc)
