"""Regression tests for the /mcp SSE route registration bug and its fix.

Live-confirmed 2026-08-31 (aryx-api-1 container logs): every /mcp GET
crashed at teardown with `TypeError: 'NoneType' object is not callable`.
Root cause: Route(path, endpoint=handle_sse) wrapped handle_sse with
Starlette's request_response(), which awaits a Response object back --
handle_sse sends its response directly via the raw ASGI `send` (through
sse.connect_sse) and never returns one.

A first version of this fix switched /mcp to Mount(app=handle_sse),
which avoids the wrapping crash but introduces a second bug: Mount
rewrites scope["root_path"] to include "/mcp" for every request routed
through it, and SseServerTransport builds the client-facing endpoint URL
as root_path + its own configured endpoint string -- an absolute
"/mcp/messages/" endpoint string there doubled up to the live-observed
"/mcp/mcp/messages/" (streamlit-sales-ui-live-310826.log, 2026-08-31).

The final fix wraps handle_sse in RawAsgiEndpoint and keeps Route:
Route.__init__ only wraps plain functions/methods with request_response()
(`inspect.isfunction`/`inspect.ismethod`); a class instance is treated as
already-ASGI and used unwrapped. Route also does exact-path matching and
never touches root_path, so the original absolute "/mcp/messages/"
endpoint string (matching the separately-registered
Mount("/mcp/messages/", ...)) is correct again.
"""
from __future__ import annotations

import inspect

from fastapi import FastAPI
from starlette.routing import Mount, Route

from aryx.api.main import _mount_mcp
from aryx.asgi_utils import RawAsgiEndpoint


def test_mcp_is_a_route_wrapping_a_raw_asgi_endpoint() -> None:
    app = FastAPI()
    _mount_mcp(app)

    mcp_routes = [r for r in app.router.routes if getattr(r, "path", None) == "/mcp"]
    assert mcp_routes, "/mcp was not mounted"
    route = mcp_routes[0]
    assert isinstance(route, Route), (
        "/mcp must stay a Route (exact-path match, no root_path rewriting) "
        "-- a Mount(app=...) here reproduces the live doubled-endpoint bug"
    )
    assert isinstance(route.endpoint, RawAsgiEndpoint), (
        "/mcp's endpoint must be wrapped in RawAsgiEndpoint so Route treats "
        "it as already-ASGI and skips request_response() wrapping -- a "
        "plain function/coroutine here reproduces the live TypeError"
    )
    # Confirms the underlying handler is genuinely raw-ASGI-shaped.
    assert list(inspect.signature(route.endpoint._app).parameters) == [
        "scope", "receive", "send",
    ]
    # PR #289 review (M1): RawAsgiEndpoint being a class instance makes
    # Route.__init__ skip its own methods=["GET"] default (only applied
    # for plain function/method endpoints) -- must be passed explicitly,
    # or every HTTP method matches instead of just GET/HEAD.
    assert route.methods == {"GET", "HEAD"}


def test_messages_mount_unaffected() -> None:
    app = FastAPI()
    _mount_mcp(app)

    messages_routes = [
        r for r in app.router.routes if getattr(r, "path", None) == "/mcp/messages"
    ]
    assert messages_routes
    assert isinstance(messages_routes[0], Mount)


def test_mcp_endpoint_string_is_absolute_matching_the_messages_mount(
    monkeypatch,
) -> None:
    """Route never rewrites root_path, so SseServerTransport must be
    configured with the full absolute path -- confirms this fix did NOT
    carry over the "make it relative" workaround from the Mount-based
    attempt, which would be wrong here and reproduce the doubled-endpoint
    bug in reverse (a relative "/messages/" would resolve to just
    "/messages/", not matching the registered "/mcp/messages/" Mount at
    all)."""
    captured_endpoints: list[str] = []

    class _RecordingSseServerTransport:
        def __init__(self, endpoint: str) -> None:
            captured_endpoints.append(endpoint)

    monkeypatch.setattr(
        "mcp.server.sse.SseServerTransport", _RecordingSseServerTransport,
    )

    app = FastAPI()
    _mount_mcp(app)

    assert captured_endpoints == ["/mcp/messages/"]


def test_mount_did_not_touch_any_other_route() -> None:
    app = FastAPI()
    _mount_mcp(app)

    non_mcp_routes = [
        r for r in app.router.routes
        if getattr(r, "path", None) not in ("/mcp", "/mcp/messages")
    ]
    assert all(isinstance(r, Route) for r in non_mcp_routes)
