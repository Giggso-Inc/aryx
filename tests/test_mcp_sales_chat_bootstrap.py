"""Tests for SalesChatService.bootstrap() -- replaces list_threads +
start + get_messages with one round-trip.

Live-confirmed 2026-08-31: Streamlit opened a brand-new MCP SSE session
per RPC call, and a single page render made 2-3 of these back-to-back
(list_threads, start, get_messages) -- the rapid connect/disconnect
churn triggered mcp.server.sse's own "Could not find session for ID"
race. bootstrap() collapses the sequence into one call/one SSE session.
"""
from __future__ import annotations

import uuid
from typing import Any

from aryx.mcp.auth import SALES_CPQ_TOOLS, McpPrincipal
from sales_streamlit.mcp_service import SalesChatService
from sales_streamlit.mcp_tools import sales_tool_specs


class FakeSalesChatStore:
    """In-memory stand-in for SalesChatStore -- no DB needed."""

    def __init__(self) -> None:
        self.threads: dict[str, dict[str, Any]] = {}
        self.messages: dict[str, list[dict[str, Any]]] = {}

    def close(self) -> None:
        pass

    def claim_thread(self, *, thread_id, actor_id, workspace_id, shay_workspace_id):
        self.threads[thread_id] = {
            "id": thread_id, "title": "New chat", "message_count": 0,
            "updated_at": None, "actor_id": actor_id,
        }
        self.messages[thread_id] = []
        return {
            "thread_id": thread_id, "actor_id": actor_id,
            "workspace_id": workspace_id, "shay_workspace_id": shay_workspace_id,
        }

    def list_threads(self, *, actor_id, workspace_id, shay_workspace_id, limit=50):
        return [t for t in self.threads.values() if t["actor_id"] == actor_id]

    def validate_owner(self, *, thread_id, actor_id, workspace_id, shay_workspace_id):
        thread = self.threads.get(thread_id)
        if thread is None or thread["actor_id"] != actor_id:
            raise PermissionError("Sales chat thread belongs to another actor")

    def list_messages(self, *, thread_id, actor_id, workspace_id, shay_workspace_id, limit=100):
        self.validate_owner(
            thread_id=thread_id, actor_id=actor_id,
            workspace_id=workspace_id, shay_workspace_id=shay_workspace_id,
        )
        return self.messages.get(thread_id, [])


def _principal() -> McpPrincipal:
    return McpPrincipal(
        token_id=1, purpose="sales_cpq",
        allowed_tools=frozenset(SALES_CPQ_TOOLS),
        workspace_id=1, shay_workspace_id="ws",
    )


def test_bootstrap_allocates_a_new_thread_when_caller_has_none() -> None:
    store = FakeSalesChatStore()
    service = SalesChatService(_principal(), store=store)

    result = service.bootstrap("alice")

    assert result["ok"] is True
    assert result["thread_id"] in store.threads
    assert result["messages"] == []
    # threads is snapshotted BEFORE the new thread is allocated -- matches
    # app.py's original list_threads() -> (conditionally) start() order,
    # so a first-time caller correctly sees an empty list here (the new
    # thread only exists in store.threads afterward, checked above).
    assert result["threads"] == []


def test_bootstrap_reuses_caller_supplied_thread_id() -> None:
    store = FakeSalesChatStore()
    service = SalesChatService(_principal(), store=store)
    first = service.bootstrap("alice")
    existing_thread_id = first["thread_id"]
    store.messages[existing_thread_id] = [{"role": "user", "content": "hi"}]

    second = service.bootstrap("alice", existing_thread_id)

    assert second["thread_id"] == existing_thread_id
    # No second thread was allocated.
    assert len(store.threads) == 1
    assert second["messages"] == [{"role": "user", "content": "hi"}]


def test_bootstrap_rejects_a_thread_id_owned_by_another_actor() -> None:
    store = FakeSalesChatStore()
    service = SalesChatService(_principal(), store=store)
    other = service.bootstrap("bob")["thread_id"]

    try:
        service.bootstrap("alice", other)
        raise AssertionError("expected PermissionError")
    except PermissionError:
        pass


def test_bootstrap_is_authorized_but_not_publicly_discoverable() -> None:
    """Mirrors sales_chat_resolve_route's pattern: gated in SALES_CPQ_TOOLS
    but absent from the discoverable list_tools() spec list -- internal
    route for sales_streamlit's own direct call path only."""
    assert "sales_chat_bootstrap" in SALES_CPQ_TOOLS
    assert "sales_chat_bootstrap" not in {spec.name for spec in sales_tool_specs()}
