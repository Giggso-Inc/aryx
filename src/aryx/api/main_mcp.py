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
    """Mount the MCP SSE transport at /mcp with bearer-token auth."""
    try:
        from mcp.server.sse import SseServerTransport
        from starlette.requests import Request
        from starlette.routing import Mount, Route

        from aryx.asgi_utils import RawAsgiEndpoint
        from aryx.mcp.auth import bind_principal, reset_principal
        from aryx.mcp.server import server

        # Absolute path -- Route (see RawAsgiEndpoint) does exact-path
        # matching and never touches scope["root_path"], so this is not
        # relative to anything; it must equal the Mount path below exactly.
        sse = SseServerTransport("/mcp/messages/")

        async def handle_sse(scope, receive, send) -> None:
            """Raw ASGI GET handler for /mcp -- must reach Starlette as an
            already-ASGI callable (via RawAsgiEndpoint), not a plain
            function/method endpoint. A plain function/method registered
            through Route(endpoint=...) gets wrapped by Starlette's
            request_response(), which awaits the endpoint expecting a
            Response object back and then calls
            `await response(scope, receive, send)`. This handler sends its
            response directly through the raw ASGI `send` (via
            `sse.connect_sse`) and never returns one, so that wrapper
            always ends up calling `None(scope, receive, send)` --
            live-confirmed 2026-08-31 crashing every /mcp SSE session at
            teardown with `TypeError: 'NoneType' object is not callable`.

            Wrapping in RawAsgiEndpoint (a callable class instance, not a
            function) makes Route's own endpoint-type check
            (`inspect.isfunction(endpoint) or inspect.ismethod(endpoint)`)
            treat it as already-ASGI and skip that wrapping entirely --
            confirmed by reading Route.__init__ directly. Deliberately
            NOT using Mount here: Mount rewrites scope["root_path"] to
            include the mount path for every request routed through it,
            which would double the "/mcp" prefix SseServerTransport
            builds its client-facing endpoint URL from (root_path + the
            endpoint string passed to SseServerTransport above) -- hit
            live as "/mcp/mcp/messages/" (streamlit-sales-ui-live-
            310826.log, 2026-08-31) in an earlier version of this fix.
            Route's exact-path matching never touches root_path, so the
            original absolute "/mcp/messages/" endpoint string is correct
            again with this approach.
            """
            request = Request(scope, receive=receive, send=send)
            principal = _authenticate_mcp(request)
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

        app.router.routes.append(
            # methods=["GET"] required explicitly -- Route only defaults
            # this to ["GET"] for plain function/method endpoints
            # (Route.__init__'s inspect.isfunction/ismethod branch);
            # RawAsgiEndpoint is a class instance, so without this,
            # methods stays None and every HTTP method matches (Route.
            # matches()'s `if self.methods and ...` is falsy for None) --
            # caught in review of PR #289.
            Route("/mcp", endpoint=RawAsgiEndpoint(handle_sse), methods=["GET"]),
        )
        app.router.routes.append(Mount("/mcp/messages/",
                                       app=sse.handle_post_message))
        logger.info("MCP mounted at /mcp")
    except Exception as exc:  # noqa: BLE001
        logger.warning("MCP mount failed: %s", exc)
