"""Authorization context for MCP requests and sales-tool isolation."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Iterable

SALES_CPQ_PURPOSE = "sales_cpq"
SALES_CPQ_TOOLS = frozenset(
    {
        "sales_chat_start",
        "sales_chat_list_threads",
        "sales_chat_get_messages",
        "sales_chat_send",
        "sales_chat_confirm",
        "sales_chat_resolve_route",
    }
)


@dataclass(frozen=True, slots=True)
class McpPrincipal:
    """Authenticated MCP token identity and its server-enforced scope."""

    token_id: int | None = None
    purpose: str = "general"
    allowed_tools: frozenset[str] = field(default_factory=frozenset)
    workspace_id: int | None = None
    shay_workspace_id: str | None = None
    expires_at: datetime | None = None

    @property
    def is_sales_cpq(self) -> bool:
        """Return whether this token is the restricted sales integration."""
        return self.purpose == SALES_CPQ_PURPOSE

    @property
    def expired(self) -> bool:
        """Return whether the token has passed its configured expiry."""
        if self.expires_at is None:
            return False
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at <= datetime.now(UTC)

    def allows(self, tool_name: str) -> bool:
        """Return whether this principal may invoke the named MCP tool."""
        if self.expired:
            return False
        if not self.is_sales_cpq:
            return True
        return tool_name in self.allowed_tools and tool_name in SALES_CPQ_TOOLS


_current_principal: ContextVar[McpPrincipal] = ContextVar(
    "aryx_mcp_principal",
    default=McpPrincipal(),
)


def current_principal() -> McpPrincipal:
    """Return the principal bound to the current MCP session."""
    return _current_principal.get()


def bind_principal(principal: McpPrincipal) -> Token[McpPrincipal]:
    """Bind a principal for an MCP session and return its reset token."""
    return _current_principal.set(principal)


def reset_principal(token: Token[McpPrincipal]) -> None:
    """Restore the principal context that existed before ``bind_principal``."""
    _current_principal.reset(token)


def visible_tool_names(
    principal: McpPrincipal,
    tool_names: Iterable[str],
) -> set[str]:
    """Return the discoverable tool names for the principal."""
    return {name for name in tool_names if principal.allows(name)}
