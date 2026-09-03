"""ShayBridgeStore's chat-thread/turn methods (mixin).

Split out of `store/shay_bridge_store.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03). Same zero-patch-risk basis as
`shay_workspace_bridge.py` — `test_shay_bridge_store.py`'s `conversation_
history` test overrides `store.list_chat_turns` as an instance attribute
(a MagicMock), which works regardless of which module the real method is
defined in.
"""
from __future__ import annotations

from typing import Any

from psycopg.types.json import Json

from aryx.config import get_settings


class _ShayChatBridgeMixin:
    """ensure/append/list chat-thread methods for ShayBridgeStore."""

    def ensure_chat_mapping(
        self,
        *,
        shay_thread_id: str,
        shay_workspace_id: str,
        aryx_workspace_id: int,
        ask_session_key: str | None = None,
    ) -> dict[str, Any]:
        """Create or update the bridge row linking a Shay thread to Aryx.

        Idempotent full-field upsert: on conflict, every field is
        overwritten with the new values (no partial-merge semantics, unlike
        `ensure_workspace_mapping`'s `sync_state` handling).

        Args:
            shay_thread_id: Shay's UUID for the chat thread.
            shay_workspace_id: Shay's UUID for the thread's workspace.
            aryx_workspace_id: The Aryx workspace id this thread maps to.
            ask_session_key: Session key for the Ask conversation state;
                defaults to `shay_thread_id` when not given.

        Returns:
            The bridge row as a dict with `shay_thread_id`,
            `aryx_workspace_id`, `shay_workspace_id`, `ask_session_key`,
            and `created` (True only for a genuinely new mapping).

        Raises:
            RuntimeError: If the insert/update leaves no row behind to read
                back (should not happen in normal operation).
        """
        ask_session_key = ask_session_key or shay_thread_id

        if get_settings().effective_db_backend() == "oci":
            # Same class of bug as ensure_workspace_mapping() above: Oracle has
            # no ON CONFLICT ... DO UPDATE, so this needs an explicit MERGE.
            # Unlike that method, this upsert is a plain full-field overwrite
            # (no COALESCE/JSON-merge semantics), so the MERGE is simpler.
            with self._pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM aryx_shay_chat_map WHERE shay_thread_id = %(shay_thread_id)s",
                    {"shay_thread_id": shay_thread_id},
                )
                pre_existing = cur.fetchone() is not None
                cur.execute(
                    """
                    MERGE INTO aryx_shay_chat_map dst
                    USING (SELECT 1 AS dual_row FROM dual) src
                    ON (dst.shay_thread_id = %(shay_thread_id)s)
                    WHEN MATCHED THEN UPDATE SET
                        aryx_workspace_id = %(aryx_workspace_id)s,
                        shay_workspace_id = %(shay_workspace_id)s,
                        ask_session_key = %(ask_session_key)s,
                        updated_at = CURRENT_TIMESTAMP
                    WHEN NOT MATCHED THEN INSERT (
                        shay_thread_id, aryx_workspace_id, shay_workspace_id, ask_session_key
                    ) VALUES (
                        %(shay_thread_id)s, %(aryx_workspace_id)s,
                        %(shay_workspace_id)s, %(ask_session_key)s
                    )
                    """,
                    {
                        "shay_thread_id": shay_thread_id,
                        "aryx_workspace_id": int(aryx_workspace_id),
                        "shay_workspace_id": shay_workspace_id,
                        "ask_session_key": ask_session_key,
                    },
                )
                cur.execute(
                    "SELECT shay_thread_id, aryx_workspace_id, shay_workspace_id, ask_session_key"
                    " FROM aryx_shay_chat_map WHERE shay_thread_id = %(shay_thread_id)s",
                    {"shay_thread_id": shay_thread_id},
                )
                row = cur.fetchone()
            if row is None:
                raise RuntimeError(f"chat map MERGE for {shay_thread_id!r} left no row behind")
            return {
                "shay_thread_id": row[0],
                "aryx_workspace_id": row[1],
                "shay_workspace_id": row[2],
                "ask_session_key": row[3],
                "created": not pre_existing,
            }

        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO aryx_shay_chat_map (
                    shay_thread_id, aryx_workspace_id, shay_workspace_id, ask_session_key
                )
                VALUES (%s::uuid, %s, %s::uuid, %s)
                ON CONFLICT (shay_thread_id) DO UPDATE
                SET aryx_workspace_id = EXCLUDED.aryx_workspace_id,
                    shay_workspace_id = EXCLUDED.shay_workspace_id,
                    ask_session_key = EXCLUDED.ask_session_key,
                    updated_at = NOW()
                RETURNING shay_thread_id::text, aryx_workspace_id, shay_workspace_id::text, ask_session_key
                """,
                (shay_thread_id, int(aryx_workspace_id), shay_workspace_id, ask_session_key),
            )
            row = cur.fetchone()
        if row is None:
            # Should not happen on Postgres (RETURNING always yields a row on
            # both INSERT and DO UPDATE) -- defensive fallback only.
            with self._pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT shay_thread_id::text, aryx_workspace_id, shay_workspace_id::text, ask_session_key"
                    " FROM aryx_shay_chat_map WHERE shay_thread_id = %s::uuid",
                    (shay_thread_id,),
                )
                row = cur.fetchone()
            if row is None:
                raise RuntimeError(f"chat map INSERT for {shay_thread_id!r} silently failed and no row found")
        return {
            "shay_thread_id": row[0],
            "aryx_workspace_id": row[1],
            "shay_workspace_id": row[2],
            "ask_session_key": row[3],
            "created": True,
        }

    def append_chat_turn(
        self,
        *,
        shay_thread_id: str,
        aryx_workspace_id: int,
        question: str,
        answer: str,
        citations: list[dict[str, Any]] | None = None,
        usage: dict[str, Any] | None = None,
        grounding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO aryx_shay_chat_turn (
                    shay_thread_id, aryx_workspace_id, question, answer, citations, usage, grounding
                )
                VALUES (%s::uuid, %s, %s, %s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (
                    shay_thread_id,
                    int(aryx_workspace_id),
                    question,
                    answer,
                    Json(citations or []),
                    Json(usage or {}),
                    Json(grounding or {}),
                ),
            )
            row = cur.fetchone()
        return {"id": row[0], "created_at": row[1]}

    def list_chat_turns(self, shay_thread_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, shay_thread_id::text, aryx_workspace_id, question, answer, citations, usage, grounding, created_at
                FROM aryx_shay_chat_turn
                WHERE shay_thread_id = %s::uuid
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (shay_thread_id, int(limit)),
            )
            rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "shay_thread_id": row[1],
                "aryx_workspace_id": row[2],
                "question": row[3],
                "answer": row[4],
                "citations": row[5] or [],
                "usage": row[6] or {},
                "grounding": row[7] or {},
                "created_at": row[8],
            }
            for row in rows
        ]

    def list_workspace_threads(
        self,
        shay_workspace_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    m.shay_thread_id::text,
                    m.aryx_workspace_id,
                    m.ask_session_key,
                    COALESCE(MAX(t.created_at), m.updated_at) AS updated_at,
                    COALESCE(
                        (
                            SELECT question
                            FROM aryx_shay_chat_turn
                            WHERE shay_thread_id = m.shay_thread_id
                            ORDER BY created_at ASC
                            LIMIT 1
                        ),
                        'New chat'
                    ) AS title,
                    COUNT(t.id) AS turn_count
                FROM aryx_shay_chat_map m
                LEFT JOIN aryx_shay_chat_turn t
                    ON t.shay_thread_id = m.shay_thread_id
                WHERE m.shay_workspace_id = %s::uuid
                GROUP BY m.shay_thread_id, m.aryx_workspace_id, m.ask_session_key, m.updated_at
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (shay_workspace_id, int(limit)),
            )
            rows = cur.fetchall()
        return [
            {
                "shay_thread_id": row[0],
                "aryx_workspace_id": row[1],
                "ask_session_key": row[2],
                "updated_at": row[3],
                "title": row[4],
                "turn_count": row[5],
            }
            for row in rows
        ]

    def conversation_history(self, shay_thread_id: str, limit_pairs: int = 6) -> list[dict[str, str]]:
        pair_limit = max(int(limit_pairs), 1)
        turns = self.list_chat_turns(shay_thread_id, limit=pair_limit)
        history: list[dict[str, str]] = []
        for turn in turns:
            history.append({"role": "user", "text": turn["question"]})
            history.append({"role": "assistant", "text": turn["answer"]})
        return history
