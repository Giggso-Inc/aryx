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

from aryx.mcp.auth import bind_principal, reset_principal
from aryx.mcp.http_auth import authenticate_authorization_header
from aryx.mcp.server import server

logger = logging.getLogger(__name__)

sse = SseServerTransport("/messages/")


async def handle_sse(request: Request) -> None:
    principal = authenticate_authorization_header(
        request.headers.get("authorization") or ""
    )
    if principal is None:
        raise HTTPException(401, "missing or invalid bearer token")
    principal_token = bind_principal(principal)
    try:
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options(),
            )
    finally:
        reset_principal(principal_token)


app = Starlette(routes=[
    Route("/sse", endpoint=handle_sse),
    Mount("/messages/", app=sse.handle_post_message),
])


def main() -> None:
    uvicorn.run("aryx.mcp.sse:app", host="0.0.0.0", port=8765, log_level="info")


if __name__ == "__main__":
    main()
