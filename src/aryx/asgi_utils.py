"""Wrap a raw ASGI callable so Starlette's `Route` mounts it unwrapped.

`Route(path, endpoint=fn)` treats `fn` differently depending on its type
(`Route.__init__`, starlette/routing.py):
  - a plain function or method -> wrapped with `request_response()`, which
    awaits `fn(request)` expecting a `Response` object back, then calls
    `await response(scope, receive, send)`.
  - anything else (e.g. a class instance) -> treated as already being an
    ASGI app and used as-is, no wrapping.

A raw ASGI handler that sends its response directly through `send` (SSE
streams, WebSocket-style protocols, ...) and never returns a `Response`
crashes the first way with `TypeError: 'NoneType' object is not callable`
once its call ends. `RawAsgiEndpoint` sidesteps this by not being a plain
function -- Route's `inspect.isfunction`/`inspect.ismethod` check is false
for a class instance, so it takes the "already ASGI" branch. Unlike
`Mount`, `Route` still does exact-path matching and never rewrites
`scope["root_path"]`, so URL-building logic inside the handler (or a
transport it drives, e.g. `mcp.server.sse.SseServerTransport`) that
assumes an unprefixed root_path keeps working unchanged.

Lives at the package root, not under `aryx/api/`: `aryx/mcp/sse.py` also
needs this, and `aryx/api/` -> `aryx/mcp/` -> `aryx/asgi_utils.py` would
be a needless cross-package dependency the other direction from the
existing `aryx/api/` -> `aryx/mcp/` one -- flagged in review of PR #289.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class RawAsgiEndpoint:
    """Adapt a raw ASGI coroutine for use as a `Route(endpoint=...)`."""

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        """Hold the wrapped ASGI callable."""
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Delegate directly -- no Response-object expectation."""
        await self._app(scope, receive, send)
