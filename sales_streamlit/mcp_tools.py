"""MCP tool contracts for the sales-facing Aryx chat facade."""

from __future__ import annotations

import mcp.types as types


def _actor_property() -> dict[str, str]:
    """Return the shared JSON Schema for the application actor identity."""
    return {
        "type": "string",
        "minLength": 1,
        "maxLength": 255,
        "description": "Stable salesperson identity supplied by the application.",
    }


def sales_tool_specs() -> list[types.Tool]:
    """Return the five discoverable Aryx-only sales integration tools.

    SALES_CPQ_TOOLS has a sixth member, sales_chat_resolve_route — it is
    auth-gated and dispatchable like the rest, but deliberately absent
    here so it stays invisible to list_tools(). It's an internal route
    used by sales_streamlit's own direct call path, not meant to be
    discovered/advertised to a generic MCP client.
    """
    return [
        types.Tool(
            name="sales_chat_start",
            description="Start an actor-owned Aryx sales configuration chat.",
            inputSchema={
                "type": "object",
                "properties": {"actor_id": _actor_property()},
                "required": ["actor_id"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="sales_chat_list_threads",
            description="List the salesperson's Aryx chat threads.",
            inputSchema={
                "type": "object",
                "properties": {
                    "actor_id": _actor_property(),
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "required": ["actor_id"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="sales_chat_get_messages",
            description="Load messages for one actor-owned Aryx chat thread.",
            inputSchema={
                "type": "object",
                "properties": {
                    "actor_id": _actor_property(),
                    "thread_id": {"type": "string", "format": "uuid"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "required": ["actor_id", "thread_id"],
                "additionalProperties": False,
            },
        ),
        *_message_tool_specs(),
    ]


def _message_tool_specs() -> list[types.Tool]:
    """Return the send and confirmation contracts."""
    common = {
        "actor_id": _actor_property(),
        "thread_id": {"type": "string", "format": "uuid"},
        "request_id": {"type": "string", "format": "uuid"},
    }
    return [
        types.Tool(
            name="sales_chat_send",
            description="Send one idempotent message to Aryx Ask.",
            inputSchema={
                "type": "object",
                "properties": {
                    **common,
                    "message": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 20000,
                    },
                },
                "required": ["actor_id", "thread_id", "request_id", "message"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="sales_chat_confirm",
            description=(
                "Confirm the relevant awaiting-approval Aryx response. Returns "
                "configData and the validated BmCatalog product route for MSI."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **common,
                    "message_id": {"type": "string", "format": "uuid"},
                },
                "required": [
                    "actor_id",
                    "thread_id",
                    "message_id",
                    "request_id",
                ],
                "additionalProperties": False,
            },
        ),
    ]
