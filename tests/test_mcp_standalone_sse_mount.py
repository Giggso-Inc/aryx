"""Regression tests for aryx/mcp/sse.py's /sse route registration.

Companion to tests/test_mcp_sse_mount.py. PR #288 review (finding C1)
flagged that this standalone module (backing the live `mcp`
docker-compose service, port 8765) had the identical Route(endpoint=...)
wrapping bug fixed for /mcp in src/aryx/api/main.py's _mount_mcp.

A first version of this module's fix used Mount("/sse", app=handle_sse)
-- but /messages/ here is a SIBLING top-level path, not nested under
/sse (unlike /mcp/messages/ under /mcp in main.py). Mount rewriting
scope["root_path"] to include "/sse" would make SseServerTransport
build "/sse/messages/" as the client-facing endpoint URL, which does
not match the actually-registered top-level "/messages/" Mount at all.
The fix instead wraps handle_sse in RawAsgiEndpoint and keeps Route,
which does exact-path matching and never touches root_path.
"""
from __future__ import annotations

import inspect

from starlette.routing import Mount, Route

from aryx.mcp.sse import app, handle_sse
from aryx.asgi_utils import RawAsgiEndpoint


def test_sse_is_a_route_wrapping_a_raw_asgi_endpoint() -> None:
    sse_routes = [r for r in app.router.routes if getattr(r, "path", None) == "/sse"]
    assert sse_routes, "/sse was not mounted"
    route = sse_routes[0]
    assert isinstance(route, Route), (
        "/sse must stay a Route (exact-path match, no root_path "
        "rewriting) -- a Mount(app=...) here would make "
        "SseServerTransport build an endpoint URL nested under /sse "
        "that doesn't match the top-level /messages/ Mount"
    )
    assert isinstance(route.endpoint, RawAsgiEndpoint)
    assert list(inspect.signature(handle_sse).parameters) == [
        "scope", "receive", "send",
    ]
    # PR #289 review (M1): must pass methods=["GET"] explicitly -- Route
    # only defaults to it for plain function/method endpoints.
    assert route.methods == {"GET", "HEAD"}


def test_messages_route_unaffected() -> None:
    messages_routes = [
        r for r in app.router.routes if getattr(r, "path", None) == "/messages"
    ]
    assert messages_routes
    assert isinstance(messages_routes[0], Mount)


def test_sse_endpoint_string_stays_relative_matching_messages_mount() -> None:
    """The endpoint string configured on the module-level `sse` transport
    (/messages/) must match the top-level Mount("/messages/", ...)
    exactly, since Route never contributes a root_path prefix here."""
    from aryx.mcp.sse import sse

    assert sse._endpoint == "/messages/"
