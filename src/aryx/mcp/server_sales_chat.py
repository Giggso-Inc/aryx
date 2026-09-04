"""Sales-chat tool dispatch for the MCP server.

Split out of `mcp/server.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

from typing import Any


def _dispatch_sales_chat(name: str, a: dict, principal: Any) -> Any:
    """Route a sales_chat_* tool call. Caller closes the service."""
    from sales_streamlit.mcp_service import SalesChatService

    service = SalesChatService(principal)
    try:
        if name == "sales_chat_start":
            return service.start(a.get("actor_id"))
        if name == "sales_chat_list_threads":
            return service.list_threads(
                a.get("actor_id"),
                int(a.get("limit") or 50),
            )
        if name == "sales_chat_get_messages":
            return service.get_messages(
                a.get("actor_id"),
                a.get("thread_id"),
                int(a.get("limit") or 100),
            )
        if name == "sales_chat_send":
            return service.send(
                actor_id=a.get("actor_id"),
                thread_id=a.get("thread_id"),
                request_id=a.get("request_id"),
                message=a.get("message"),
            )
        if name == "sales_chat_confirm":
            return service.confirm(
                actor_id=a.get("actor_id"),
                thread_id=a.get("thread_id"),
                message_id=a.get("message_id"),
                request_id=a.get("request_id"),
            )
        if name == "sales_chat_resolve_route":
            return service.resolve_route(
                actor_id=a.get("actor_id"),
                thread_id=a.get("thread_id"),
            )
        if name == "sales_chat_bootstrap":
            return service.bootstrap(
                a.get("actor_id"),
                a.get("thread_id"),
            )
    finally:
        service.close()
