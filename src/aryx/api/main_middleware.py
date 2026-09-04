"""Request-timing ASGI middleware for the combined Aryx API app.

Split out of `api/main.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class _RequestTimingMiddleware:
    """ASGI middleware: log a timestamped start/end line for every HTTP
    request, so a stuck request shows a "started, never finished" line
    instead of silence between whatever the request handler itself logs.
    Confirmed need (2026-08-14 incident): a POST /api/ask/threads/message
    took 15 min and a GET /api/graph took 5 min then 502'd, with nothing in
    aryx.cpq.engine/ask_api logs to show WHERE either request was stuck --
    only the access log line printed, and only after the fact, with no
    timestamp on it at all (see uvicorn.access fix in main_logging.py)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

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

        async def _send(message) -> None:
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
