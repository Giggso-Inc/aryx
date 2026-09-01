"""Tests for offloading MCP tool dispatch off the event loop.

Live-verified: call_tool() called _dispatch() (fully synchronous, can run
several seconds on CPQ-heavy tools -- load_product_config alone timed at
6.5s in production) inline, blocking this process's single asyncio event
loop for that whole duration -- freezing every other concurrent user's
SSE/REST/MCP traffic. Switched to asyncio.to_thread, which also
propagates the current contextvars.Context (needed for
aryx.mcp.auth.current_principal()) into the worker thread.
"""
from __future__ import annotations

import asyncio
import threading

import aryx.mcp.server as server_module
from aryx.mcp.auth import McpPrincipal, bind_principal, current_principal


def test_call_tool_runs_dispatch_on_a_worker_thread(monkeypatch) -> None:
    main_thread = threading.current_thread()
    seen_threads: list[threading.Thread] = []

    def fake_dispatch(name, arguments):
        seen_threads.append(threading.current_thread())
        return {"ok": True}

    monkeypatch.setattr(server_module, "_dispatch", fake_dispatch)

    asyncio.run(server_module.call_tool("list", {}))

    assert seen_threads, "_dispatch was never called"
    assert seen_threads[0] is not main_thread, (
        "_dispatch must run off the event loop's thread -- calling it "
        "inline blocks every other concurrent user for its full duration"
    )


def test_call_tool_propagates_current_principal_into_worker_thread(
    monkeypatch,
) -> None:
    """asyncio.to_thread (not loop.run_in_executor) is required specifically
    because it propagates contextvars into the worker thread -- confirms
    current_principal() still resolves correctly there."""
    principal = McpPrincipal(
        token_id=1, purpose="sales_cpq",
        allowed_tools=frozenset({"list"}), workspace_id=1, shay_workspace_id="ws",
    )
    seen_principals: list[McpPrincipal] = []

    def fake_dispatch(name, arguments):
        seen_principals.append(current_principal())
        return {"ok": True}

    monkeypatch.setattr(server_module, "_dispatch", fake_dispatch)

    async def _run():
        token = bind_principal(principal)
        try:
            await server_module.call_tool("list", {})
        finally:
            from aryx.mcp.auth import reset_principal
            reset_principal(token)

    asyncio.run(_run())

    assert seen_principals == [principal]
