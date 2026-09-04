"""Aryx MCP server — stdio + SSE. Wraps REST so any MCP host can drive it.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`mcp/server_http.py` (`_get`/`_post` REST helpers), `mcp/server_workspace.py`
(`_enrich_workspace`/`_axiom_summary`), and `mcp/server_sales_chat.py`
(sales_chat_* tool dispatch), all re-imported here. Zero whitebox test
patches exist anywhere against `aryx.mcp.server.*` (confirmed via grep),
so the split was purely mechanical. `_dispatch`/`call_tool`/`list_tools`
stay here as the tool-routing entry points.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from aryx.mcp.auth import current_principal
from aryx.mcp.server_http import _get, _post
from aryx.mcp.server_sales_chat import _dispatch_sales_chat
from aryx.mcp.server_workspace import _enrich_workspace
from aryx.mcp.tools import tool_specs

logger = logging.getLogger(__name__)

_DEFAULT_WS = int(os.environ.get("ARYX_MCP_DEFAULT_WORKSPACE", "1"))
server = Server("aryx")


def _ws(args: dict[str, Any]) -> int:
    """Resolve workspace_id from args or env default."""
    return int(args.get("workspace_id") or _DEFAULT_WS)


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    principal = current_principal()
    return [spec for spec in tool_specs() if principal.allows(spec.name)]


def _dispatch(name: str, a: dict) -> Any:
    """Route a tool call: list, ask, or act (request-only)."""
    principal = current_principal()
    if not principal.allows(name):
        return {
            "ok": False,
            "error": "tool_not_allowed",
            "message": f"MCP token is not authorized for tool {name!r}",
        }
    if name.startswith("sales_chat_"):
        return _dispatch_sales_chat(name, a, principal)
    if name == "list":
        workspaces = _get("/admin/workspaces?workspace_id=1") or []
        return [_enrich_workspace(ws) for ws in workspaces]
    if name == "ask":
        return _post("/ask", {
            "question": a["question"],
            "history": a.get("history") or [],
            "workspace_id": _ws(a),
        })
    if name == "act":
        from aryx.mcp.act import _act
        return _act(a)
    if name.startswith("workspace_") or name.startswith("brief_"):
        from aryx.mcp.onboard import dispatch as _onboard
        return _onboard(name, a)
    if name.startswith("datasource_"):
        from aryx.mcp.datasource import dispatch as _ds
        return _ds(name, a)
    if name.startswith("ingest_") or name == "entities_preview":
        from aryx.mcp.ingest_hitl import dispatch as _hitl
        return _hitl(name, a)
    if name.startswith("ontology_"):
        from aryx.mcp.ontology import dispatch as _ont
        return _ont(name, a)
    return {"ok": False, "error": "unknown_tool", "message": f"unknown tool: {name}"}


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        # _dispatch is fully synchronous and can run for several seconds
        # on CPQ-heavy tools (e.g. sales_chat_send -> run_ask ->
        # load_product_config, live-timed at 6.5s in production) --
        # calling it inline here would block this process's single
        # asyncio event loop for that whole duration, freezing every
        # other concurrent user's SSE/REST/MCP traffic. asyncio.to_thread
        # (not loop.run_in_executor) is required specifically because it
        # propagates the current contextvars.Context into the worker
        # thread via copy_context() -- current_principal() (a ContextVar
        # bound in handle_sse before dispatch reaches here) would
        # otherwise silently break inside the offloaded call.
        # Thread-safety confirmed: CpqEngine has no instance state at
        # all; engine.py's module-level rule/layout caches are plain
        # dicts with no lock, but CPython's GIL makes individual
        # get/set operations atomic, and every cache key's value is
        # deterministically derived from that key alone -- the only
        # possible race is benign redundant recomputation on a
        # simultaneous cache miss, never corrupted or incorrect data.
        result = await asyncio.to_thread(_dispatch, name, arguments or {})
    except (ValueError, PermissionError) as exc:
        result = {
            "ok": False,
            "error": "invalid_request",
            "message": str(exc)[:500],
            "tool": name,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp tool failed name=%s error=%s", name, exc)
        if name.startswith("sales_chat_"):
            result = {
                "ok": False,
                "error": "tool_failed",
                "message": "Aryx could not complete this request.",
                "tool": name,
            }
        else:
            result = {"error": str(exc), "tool": name}
    return [types.TextContent(type="text",
            text=json.dumps(result, indent=2, default=str))]


async def main() -> None:
    """Run as a stdio MCP server (for local Claude Desktop)."""
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())
