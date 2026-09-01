"""Actor ownership and transcript persistence for sales conversations."""

from __future__ import annotations

from typing import Any

from aryx.queries import load
from aryx.store.ask_thread_store import ASK_CHANNEL_NAME, AryxAskThreadStore
from aryx.store.pool import get_pool


class SalesChatStore:
    """Enforce salesperson ownership around the existing Ask thread store."""

    def __init__(self, dsn: str) -> None:
        """Acquire the shared pool and wrapped Ask thread store."""
        self._pool = get_pool(dsn)
        self._ask = AryxAskThreadStore(dsn)

    def close(self) -> None:
        """No-op: shared pool lifecycle is managed globally."""

    def claim_thread(
        self,
        *,
        thread_id: str,
        actor_id: str,
        workspace_id: int,
        shay_workspace_id: str,
    ) -> dict[str, Any]:
        """Claim a new thread or validate its existing immutable owner."""
        self._ask.validate_mapping(workspace_id, shay_workspace_id)
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                load("sales_chat_claim_thread"),
                (thread_id, actor_id, workspace_id, shay_workspace_id),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(load("sales_chat_select_thread"), (thread_id,))
                row = cur.fetchone()
        if row is None:
            raise ValueError("Unable to claim the sales chat thread")
        owner = {
            "thread_id": str(row[0]),
            "actor_id": str(row[1]),
            "workspace_id": int(row[2]),
            "shay_workspace_id": str(row[3]),
        }
        expected = {
            "thread_id": thread_id,
            "actor_id": actor_id,
            "workspace_id": int(workspace_id),
            "shay_workspace_id": shay_workspace_id,
        }
        if owner != expected:
            raise PermissionError("Sales chat thread belongs to another actor")
        return owner

    def validate_owner(
        self,
        *,
        thread_id: str,
        actor_id: str,
        workspace_id: int,
        shay_workspace_id: str,
    ) -> None:
        """Reject access unless the complete thread scope matches."""
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(load("sales_chat_select_thread"), (thread_id,))
            row = cur.fetchone()
        if row is None:
            raise ValueError("Sales chat thread was not found")
        if (
            str(row[1]) != actor_id
            or int(row[2]) != int(workspace_id)
            or str(row[3]) != shay_workspace_id
        ):
            raise PermissionError("Sales chat thread belongs to another actor")

    def list_threads(
        self,
        *,
        actor_id: str,
        workspace_id: int,
        shay_workspace_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List only the actor-owned Ask threads in the token-bound scope."""
        self._ask.validate_mapping(workspace_id, shay_workspace_id)
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                load("sales_chat_list_threads"),
                (
                    actor_id,
                    workspace_id,
                    shay_workspace_id,
                    ASK_CHANNEL_NAME,
                    min(max(int(limit), 1), 200),
                ),
            )
            rows = cur.fetchall()
        return [
            {
                "id": str(row[0]),
                "title": str(row[1]),
                "message_count": int(row[2]),
                "updated_at": row[3],
            }
            for row in rows
        ]

    def list_messages(
        self,
        *,
        thread_id: str,
        actor_id: str,
        workspace_id: int,
        shay_workspace_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return a transcript only after the actor ownership check."""
        self.validate_owner(
            thread_id=thread_id,
            actor_id=actor_id,
            workspace_id=workspace_id,
            shay_workspace_id=shay_workspace_id,
        )
        try:
            return self._ask.list_messages(
                workspace_id,
                shay_workspace_id,
                thread_id,
                limit=min(max(int(limit), 1), 200),
            )
        except ValueError:
            # Ownership is claimed in aryx_sales_chat_thread at start(), but
            # the underlying gg_threads row is only materialized by Aryx Ask
            # on the first send. A claimed, not-yet-materialized thread has
            # no transcript yet rather than being an invalid thread.
            return []

    def latest_assistant(
        self,
        *,
        thread_id: str,
        actor_id: str,
        workspace_id: int,
        shay_workspace_id: str,
    ) -> dict[str, Any] | None:
        """Return the latest assistant message within the actor scope."""
        self.validate_owner(
            thread_id=thread_id,
            actor_id=actor_id,
            workspace_id=workspace_id,
            shay_workspace_id=shay_workspace_id,
        )
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                load("sales_chat_latest_assistant"),
                (thread_id, actor_id, workspace_id, shay_workspace_id),
            )
            row = cur.fetchone()
        if row is None:
            return None
        metadata = row[2] or {}
        return {
            "id": str(row[0]),
            "content": str(row[1]),
            "session_data": metadata.get("session_data") or {},
            "cpq_payload": metadata.get("cpq_payload"),
            "request_id": str(row[3]),
            "created_at": row[4],
        }

    @property
    def ask(self) -> AryxAskThreadStore:
        """Return the wrapped Ask store for idempotent message persistence."""
        return self._ask
