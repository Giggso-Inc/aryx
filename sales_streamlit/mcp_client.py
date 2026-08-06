"""Synchronous facade over the Aryx MCP SSE client for the sales app."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from mcp import ClientSession
from mcp.client.sse import sse_client


@dataclass(frozen=True, slots=True)
class SalesMcpSettings:
    """Server-side Aryx MCP endpoint and scoped integration key."""

    url: str
    api_key: str
    allow_http: bool = False
    connect_timeout: float = 10.0
    # A single sales_chat_send call can drive several sequential LLM calls
    # (intent, term extraction, family match, config load) server-side;
    # local CPU-bound Ollama can take several minutes for that whole chain.
    read_timeout: float = 1800.0

    @classmethod
    def from_env(cls, api_key: str | None = None) -> "SalesMcpSettings":
        """Load the MCP endpoint from server-side environment.

        The bearer token carries a fixed workspace scope (baked in at
        issuance via POST /admin/mcp/tokens), so multi-workspace
        deployments pass the selected workspace's token explicitly here
        instead of relying solely on ARYX_SALES_MCP_API_KEY.
        """
        settings = cls(
            url=os.environ.get("ARYX_SALES_MCP_URL", "").strip(),
            api_key=(
                api_key
                if api_key is not None
                else os.environ.get("ARYX_SALES_MCP_API_KEY", "")
            ).strip(),
            allow_http=os.environ.get("ARYX_SALES_MCP_ALLOW_HTTP", "0") == "1",
            connect_timeout=float(
                os.environ.get("ARYX_SALES_MCP_CONNECT_TIMEOUT", "10")
            ),
            read_timeout=float(
                os.environ.get("ARYX_SALES_MCP_READ_TIMEOUT", "1800")
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Reject missing credentials and unsafe production transport."""
        if not self.url or not self.api_key:
            raise ValueError("Aryx sales MCP URL and API key must be configured")
        parsed = urlparse(self.url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("Aryx sales MCP URL must be an absolute HTTP(S) URL")
        if parsed.scheme != "https" and not self.allow_http:
            raise ValueError("Aryx sales MCP URL must use HTTPS")


class SalesMcpClient:
    """Call only sales MCP tools through one authenticated SSE session per turn."""

    def __init__(self, settings: SalesMcpSettings) -> None:
        """Validate and retain the server-side MCP connection settings."""
        settings.validate()
        self._settings = settings

    async def _call_async(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Open an authenticated MCP session and call one sales tool."""
        headers = {"Authorization": f"Bearer {self._settings.api_key}"}
        async with sse_client(
            self._settings.url,
            headers=headers,
            timeout=self._settings.connect_timeout,
            sse_read_timeout=self._settings.read_timeout,
        ) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(
                    tool_name,
                    arguments,
                    read_timeout_seconds=timedelta(
                        seconds=self._settings.read_timeout
                    ),
                )
        texts = [
            content.text
            for content in result.content
            if getattr(content, "type", "") == "text"
        ]
        if not texts:
            raise RuntimeError("Aryx MCP returned no text result")
        try:
            payload = json.loads(texts[0])
        except json.JSONDecodeError as exc:
            raise RuntimeError("Aryx MCP returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Aryx MCP returned an unexpected result")
        if payload.get("ok") is False or payload.get("error"):
            raise RuntimeError(
                str(payload.get("message") or payload.get("error") or "Aryx failed")
            )
        return payload

    def call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run one MCP tool call from Streamlit's synchronous execution model."""
        return asyncio.run(self._call_async(tool_name, arguments))

    def start(self, actor_id: str) -> dict[str, Any]:
        """Start an actor-owned chat."""
        return self.call("sales_chat_start", {"actor_id": actor_id})

    def list_threads(self, actor_id: str) -> list[dict[str, Any]]:
        """List the actor's chats."""
        return self.call(
            "sales_chat_list_threads",
            {"actor_id": actor_id},
        ).get("threads", [])

    def get_messages(
        self,
        actor_id: str,
        thread_id: str,
    ) -> list[dict[str, Any]]:
        """Load an actor-owned transcript."""
        return self.call(
            "sales_chat_get_messages",
            {"actor_id": actor_id, "thread_id": thread_id, "limit": 200},
        ).get("messages", [])

    def send(
        self,
        actor_id: str,
        thread_id: str,
        request_id: str,
        message: str,
    ) -> dict[str, Any]:
        """Send one idempotent chat turn."""
        return self.call(
            "sales_chat_send",
            {
                "actor_id": actor_id,
                "thread_id": thread_id,
                "request_id": request_id,
                "message": message,
            },
        )

    def confirm(
        self,
        actor_id: str,
        thread_id: str,
        message_id: str,
        request_id: str,
    ) -> dict[str, Any]:
        """Confirm an awaiting-approval assistant message."""
        return self.call(
            "sales_chat_confirm",
            {
                "actor_id": actor_id,
                "thread_id": thread_id,
                "message_id": message_id,
                "request_id": request_id,
            },
        )

    def resolve_route(self, actor_id: str, thread_id: str) -> dict[str, Any]:
        """Read-only BmCatalog route lookup — never re-runs the CPQ turn."""
        return self.call(
            "sales_chat_resolve_route",
            {"actor_id": actor_id, "thread_id": thread_id},
        )
