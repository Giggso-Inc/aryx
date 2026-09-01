"""MCP SSE server — HTTP transport for server-side deployment (Inc 11).

Run with: uvicorn aryx.mcp.sse:app --host 0.0.0.0 --port 8765
Claude Desktop config:
  { "mcpServers": { "aryx": { "url": "http://<host>:8765/sse" } } }
"""
from __future__ import annotations

import logging

import uvicorn
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.routing import Mount, Route

from aryx.asgi_utils import RawAsgiEndpoint
from aryx.mcp.auth import bind_principal, reset_principal
from aryx.mcp.http_auth import authenticate_authorization_header
from aryx.mcp.server import server

logger = logging.getLogger(__name__)

sse = SseServerTransport("/messages/")


async def handle_sse(scope, receive, send) -> None:
    """Raw ASGI GET handler for /sse -- must reach Starlette as an
    already-ASGI callable (via RawAsgiEndpoint), not a plain
    function/method endpoint. A plain function/method registered through
    Route(endpoint=...) gets wrapped by Starlette's request_response(),
    which awaits the endpoint expecting a Response object back and then
    calls `await response(scope, receive, send)`. This handler sends its
    response directly through the raw ASGI `send` (via `sse.connect_sse`)
    and never returns one, so that wrapper always ends up calling
    `None(scope, receive, send)` -- same crash live-confirmed 2026-08-31
    on the sibling /mcp endpoint in aryx/api/main.py's _mount_mcp.

    An earlier version of this fix used `Mount("/sse", app=handle_sse)`
    instead -- that avoids the wrapping crash, but Mount also rewrites
    scope["root_path"] to include "/sse" for every request routed
    through it. SseServerTransport builds the client-facing endpoint URL
    as root_path + its own configured endpoint string ("/messages/"),
    which would then resolve to "/sse/messages/" -- NOT the actually-
    registered top-level "/messages/" Mount below (they are siblings,
    not nested). RawAsgiEndpoint + Route sidesteps this: Route does
    exact-path matching and never touches root_path, so the original
    "/messages/" endpoint string stays correct.
    """
    request = Request(scope, receive=receive, send=send)
    principal = authenticate_authorization_header(
        request.headers.get("authorization") or ""
    )
    if principal is None:
        raise HTTPException(401, "missing or invalid bearer token")
    principal_token = bind_principal(principal)
    try:
        async with sse.connect_sse(scope, receive, send) as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options(),
            )
    finally:
        reset_principal(principal_token)


app = Starlette(routes=[
    # methods=["GET"] required explicitly -- Route only defaults this to
    # ["GET"] for plain function/method endpoints (Route.__init__'s
    # inspect.isfunction/ismethod branch); RawAsgiEndpoint is a class
    # instance, so without this, methods stays None and every HTTP
    # method matches -- caught in review of PR #289.
    Route("/sse", endpoint=RawAsgiEndpoint(handle_sse), methods=["GET"]),
    Mount("/messages/", app=sse.handle_post_message),
])


def main() -> None:
    uvicorn.run("aryx.mcp.sse:app", host="0.0.0.0", port=8765, log_level="info")


if __name__ == "__main__":
    main()
