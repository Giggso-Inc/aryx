"""Regression tests for the /mcp route registration and its stateless
Streamable HTTP transport (ported from dev-rv-msi's 1b269664).

Previously this covered the SseServerTransport-based mount and its
GET-then-POST session-registry handshake. That transport is now gone
(see main_mcp.py's docstring for the cross-worker 404 bug it caused);
these tests cover the replacement instead:
StreamableHTTPSessionManager(stateless=True), mounted as a single Route
accepting GET/POST/DELETE, with no separate /mcp/messages Mount left to
desync a session_id across workers.
"""
from __future__ import annotations

import inspect

from fastapi import FastAPI
from starlette.routing import Route

from aryx.api.main import _mount_mcp
from aryx.asgi_utils import RawAsgiEndpoint


def test_mcp_is_a_route_wrapping_a_raw_asgi_endpoint() -> None:
    app = FastAPI()
    _mount_mcp(app)

    mcp_routes = [r for r in app.router.routes if getattr(r, "path", None) == "/mcp"]
    assert mcp_routes, "/mcp was not mounted"
    route = mcp_routes[0]
    assert isinstance(route, Route), (
        "/mcp must stay a Route (exact-path match, no root_path rewriting), "
        "same reasoning as the SSE-era fix this replaces"
    )
    assert isinstance(route.endpoint, RawAsgiEndpoint), (
        "/mcp's endpoint must be wrapped in RawAsgiEndpoint so Route treats "
        "it as already-ASGI and skips request_response() wrapping -- a "
        "plain function/coroutine here reproduces the live TypeError this "
        "was originally fixed for"
    )
    # Confirms the underlying handler is genuinely raw-ASGI-shaped.
    assert list(inspect.signature(route.endpoint._app).parameters) == [
        "scope", "receive", "send",
    ]
    # Stateless mode carries every real request as a POST; GET/DELETE are
    # accepted too since StreamableHTTPSessionManager.handle_request
    # dispatches on method internally and the mcp client library may probe
    # either. No more session_id to register via a separate GET. HEAD is
    # Starlette's own Route.__init__ auto-adding it whenever GET is present
    # (not something this mount configures).
    assert route.methods == {"GET", "HEAD", "POST", "DELETE"}


def test_no_separate_messages_mount() -> None:
    """The old /mcp/messages Mount (a second endpoint the SSE transport
    posted session-scoped follow-ups to) must not exist -- stateless
    Streamable HTTP has no second endpoint and no session_id to route by."""
    app = FastAPI()
    _mount_mcp(app)

    messages_routes = [
        r for r in app.router.routes if "messages" in (getattr(r, "path", "") or "")
    ]
    assert not messages_routes


def test_mount_sets_session_manager_on_app_state() -> None:
    """_lifespan (main_lifespan.py) needs app.state.mcp_session_manager to
    enter/exit StreamableHTTPSessionManager's task group around app
    startup -- confirms _mount_mcp actually stashes it there."""
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    app = FastAPI()
    _mount_mcp(app)

    assert isinstance(app.state.mcp_session_manager, StreamableHTTPSessionManager)


def test_mount_did_not_touch_any_other_route() -> None:
    app = FastAPI()
    _mount_mcp(app)

    non_mcp_routes = [
        r for r in app.router.routes if getattr(r, "path", None) != "/mcp"
    ]
    assert all(isinstance(r, Route) for r in non_mcp_routes)
