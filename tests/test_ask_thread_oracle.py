"""Unit tests for the Oracle port of Ask-thread persistence.

Covers _as_json() (CLOB-vs-JSONB normalization) and _insert_message_oracle()
(the xmax-free retry-safety reimplementation) -- see
docs/OCI_POSTGRES_PARITY_AUDIT.md for the design this implements.
"""
from __future__ import annotations

import json
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


def _stub_psycopg() -> None:
    """Full stub (psycopg + psycopg_pool) -- aryx.store.__init__ imports
    entity_store -> pool.py -> psycopg_pool -> psycopg.Connection, so a
    partial stub isn't enough once the real psycopg_pool package is
    installed (matches test_oracle_pool.py's stub)."""
    if "psycopg" in sys.modules:
        return
    psycopg = types.ModuleType("psycopg")
    psycopg.connect = MagicMock()
    psycopg.Connection = MagicMock()
    psycopg.Cursor = MagicMock()
    psycopg_sql = types.ModuleType("psycopg.sql")
    psycopg_sql.SQL = MagicMock()
    psycopg_sql.Identifier = MagicMock()
    psycopg.sql = psycopg_sql
    psycopg_types = types.ModuleType("psycopg.types")
    psycopg_types_json = types.ModuleType("psycopg.types.json")
    psycopg_types_json.Json = lambda obj, dumps=None: obj
    psycopg_types.json = psycopg_types_json
    psycopg.types = psycopg_types
    sys.modules.update({
        "psycopg": psycopg, "psycopg.sql": psycopg_sql,
        "psycopg.types": psycopg_types, "psycopg.types.json": psycopg_types_json,
    })
    psycopg_pool = types.ModuleType("psycopg_pool")
    psycopg_pool.ConnectionPool = MagicMock()
    sys.modules["psycopg_pool"] = psycopg_pool


_stub_psycopg()

from aryx.store.ask_thread_helpers import _as_json
from aryx.store.ask_thread_oracle_insert import _insert_message_oracle  # noqa: E402


class TestAsJson(unittest.TestCase):
    """_as_json normalizes CLOB-text (Oracle) and already-parsed (Postgres) alike."""

    def test_dict_passthrough(self) -> None:
        d = {"a": 1}
        self.assertIs(_as_json(d), d)

    def test_list_passthrough(self) -> None:
        lst = [1, 2]
        self.assertIs(_as_json(lst), lst)

    def test_json_string_parsed(self) -> None:
        self.assertEqual(_as_json('{"a": 1}'), {"a": 1})

    def test_none_passthrough(self) -> None:
        self.assertIsNone(_as_json(None))

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(_as_json(""))
        self.assertIsNone(_as_json("   "))

    def test_invalid_json_string_returned_as_is(self) -> None:
        self.assertEqual(_as_json("not json"), "not json")


class _FakeCursor:
    """Records execute() calls by query name; fetchone() drains a per-name queue.

    load() is patched (module-level, per test) to return the query name
    unchanged, so this fake can dispatch by name without needing real SQL.
    """

    def __init__(self, responses: dict[str, list]) -> None:
        self._responses = {k: list(v) for k, v in responses.items()}
        self.calls: list[tuple[str, tuple]] = []
        self._last = None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.calls.append((sql, params))
        self._last = sql

    def fetchone(self):
        queue = self._responses.get(self._last)
        if not queue:
            return None
        return queue.pop(0)


def _params(
    thread_id="t1", message_id="m1", content="hello", message_type="user",
    request_id="r1", is_ai_processed=False, ai_provider=None, ai_model=None,
    ai_processing_time=None, metadata=None, citations=None, usage=None,
):
    return (
        thread_id, message_id, content, message_type, thread_id, request_id,
        is_ai_processed, ai_provider, ai_model, ai_processing_time,
        metadata or {}, citations or [], usage or {},
    )


class TestInsertMessageOracleFreshInsert(unittest.TestCase):
    def test_no_existing_row_inserts_fresh(self) -> None:
        cur = _FakeCursor({
            "ask_thread_lock_thread": [("t1",)],
            "ask_thread_select_existing_message": [None],
            "ask_thread_next_sequence": [(3,)],
        })
        import aryx.store.ask_thread_oracle_insert as mod
        orig_load = mod.load
        mod.load = lambda name: name
        try:
            result = _insert_message_oracle(cur, _params())
        finally:
            mod.load = orig_load
        # inserted=True on the genuine-insert branch -- callers gate
        # ask_thread_touch_channel on this to avoid double-counting a retry
        # that hits the update branch instead.
        self.assertEqual(result, ("m1", 3, True, "hello"))
        # Confirm the insert actually ran (last call).
        self.assertEqual(cur.calls[-1][0], "ask_thread_insert_message_oracle")


class TestInsertMessageOracleSystemMessage(unittest.TestCase):
    def test_system_message_always_overwrites(self) -> None:
        cur = _FakeCursor({
            "ask_thread_lock_thread": [("t1",)],
            "ask_thread_select_existing_message": [
                ("existing-id", 5, "old answer", "{}", datetime.now(timezone.utc)),
            ],
        })
        import aryx.store.ask_thread_oracle_insert as mod
        orig_load = mod.load
        mod.load = lambda name: name
        try:
            result = _insert_message_oracle(cur, _params(message_type="system", content="new answer"))
        finally:
            mod.load = orig_load
        self.assertEqual(result, ("existing-id", 5, False, "new answer"))
        self.assertEqual(cur.calls[-1][0], "ask_thread_update_message_oracle")


class TestInsertMessageOracleUserRetrySafety(unittest.TestCase):
    def _run(self, existing_row, content="hello"):
        cur = _FakeCursor({
            "ask_thread_lock_thread": [("t1",)],
            "ask_thread_select_existing_message": [existing_row],
            "ask_thread_has_failed_response": [None],
        })
        import aryx.store.ask_thread_oracle_insert as mod
        orig_load = mod.load
        mod.load = lambda name: name
        try:
            result = _insert_message_oracle(cur, _params(content=content))
        finally:
            mod.load = orig_load
        return result, cur

    def test_different_question_same_request_id_rejected(self) -> None:
        existing = ("id1", 2, "a completely different question", "{}", datetime.now(timezone.utc))
        result, cur = self._run(existing, content="hello")
        self.assertIsNone(result)
        # Must reject before even checking status -- no update call issued.
        self.assertNotIn("ask_thread_update_message_oracle", [c[0] for c in cur.calls])

    def test_same_question_status_failed_overwrites(self) -> None:
        metadata = json.dumps({"request_status": "failed"})
        existing = ("id1", 2, "hello", metadata, datetime.now(timezone.utc))
        result, cur = self._run(existing)
        self.assertEqual(result, ("id1", 2, False, "hello"))
        self.assertEqual(cur.calls[-1][0], "ask_thread_update_message_oracle")

    def test_same_question_status_completed_rejected(self) -> None:
        metadata = json.dumps({"request_status": "completed"})
        existing = ("id1", 2, "hello", metadata, datetime.now(timezone.utc))
        result, _cur = self._run(existing)
        self.assertIsNone(result)

    def test_same_question_no_status_with_failed_response_overwrites(self) -> None:
        cur = _FakeCursor({
            "ask_thread_lock_thread": [("t1",)],
            "ask_thread_select_existing_message": [
                ("id1", 2, "hello", json.dumps({}), datetime.now(timezone.utc)),
            ],
            "ask_thread_has_failed_response": [("found",)],
        })
        import aryx.store.ask_thread_oracle_insert as mod
        orig_load = mod.load
        mod.load = lambda name: name
        try:
            result = _insert_message_oracle(cur, _params())
        finally:
            mod.load = orig_load
        self.assertEqual(result, ("id1", 2, False, "hello"))

    def test_same_question_no_status_no_failed_response_rejected(self) -> None:
        cur = _FakeCursor({
            "ask_thread_lock_thread": [("t1",)],
            "ask_thread_select_existing_message": [
                ("id1", 2, "hello", json.dumps({}), datetime.now(timezone.utc)),
            ],
            "ask_thread_has_failed_response": [None],
        })
        import aryx.store.ask_thread_oracle_insert as mod
        orig_load = mod.load
        mod.load = lambda name: name
        try:
            result = _insert_message_oracle(cur, _params())
        finally:
            mod.load = orig_load
        self.assertIsNone(result)

    def test_in_progress_stale_overwrites(self) -> None:
        stale = datetime.now(timezone.utc) - timedelta(minutes=25)
        metadata = json.dumps({"request_status": "in_progress"})
        existing = ("id1", 2, "hello", metadata, stale)
        result, _cur = self._run(existing)
        self.assertEqual(result, ("id1", 2, False, "hello"))

    def test_in_progress_fresh_rejected(self) -> None:
        fresh = datetime.now(timezone.utc) - timedelta(minutes=2)
        metadata = json.dumps({"request_status": "in_progress"})
        existing = ("id1", 2, "hello", metadata, fresh)
        result, _cur = self._run(existing)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
