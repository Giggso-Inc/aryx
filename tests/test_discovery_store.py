"""Unit tests for DiscoveryStore — stubbed pool, no live DB."""
from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ── Stub heavy DB dependencies before any aryx import ────────────────────────

def _stub_psycopg() -> None:
    if "psycopg" in sys.modules:
        return
    psycopg = types.ModuleType("psycopg")
    psycopg.connect = MagicMock()
    sys.modules["psycopg"] = psycopg
    # psycopg.types.json.Json
    psycopg_types = types.ModuleType("psycopg.types")
    psycopg_json = types.ModuleType("psycopg.types.json")
    psycopg_json.Json = MagicMock()
    psycopg_types.json = psycopg_json
    sys.modules["psycopg.types"] = psycopg_types
    sys.modules["psycopg.types.json"] = psycopg_json
    # psycopg_pool.ConnectionPool
    pool_mod = types.ModuleType("psycopg_pool")
    pool_mod.ConnectionPool = MagicMock()
    sys.modules["psycopg_pool"] = pool_mod
    # falkordb
    falkor = types.ModuleType("falkordb")
    falkor.FalkorDB = MagicMock()
    sys.modules["falkordb"] = falkor


_stub_psycopg()

from aryx.store.discovery_store import DiscoveryStore  # noqa: E402

_DSN = "postgresql://test"
_DID = "abc123"
_WS = 1


_PATCHES: list[Any] = []


def setup_module(module: Any) -> None:
    """Patch load and get_pool at module level for the duration of the test run."""
    p1 = patch("aryx.store.discovery_store.load", return_value="SELECT 1")
    p2 = patch("aryx.store.pool.get_pool")
    _PATCHES.extend([p1.start(), p2.start()])


def teardown_module(module: Any) -> None:
    patch.stopall()


def _make_store() -> tuple[DiscoveryStore, MagicMock]:
    """Return (store, mock_pool). get_pool already patched by setup_module."""
    mock_pool = MagicMock()
    with patch("aryx.store.discovery_store.get_pool", return_value=mock_pool):
        store = DiscoveryStore(_DSN)
    return store, mock_pool


def _cursor_returning(rows: list[tuple] | tuple | None) -> MagicMock:
    """Fake cursor whose fetchone/fetchall return the given rows."""
    cur = MagicMock()
    if isinstance(rows, list):
        cur.fetchall.return_value = rows
        cur.fetchone.return_value = rows[0] if rows else None
    else:
        cur.fetchone.return_value = rows
        cur.fetchall.return_value = [rows] if rows else []
    return cur


def _conn_with_cursor(cursor: MagicMock) -> MagicMock:
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn


def _pool_with_conn(conn: MagicMock) -> MagicMock:
    pool = MagicMock()
    pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    pool.connection.return_value.__exit__ = MagicMock(return_value=False)
    return pool


# ── Core behaviour ───────────────────────────────────────────────────────────

def test_put_and_get_returns_row() -> None:
    store, mock_pool = _make_store()
    row = (_DID, _WS, "pending", '{"k": 1}', '{"types": []}', 1,
           '{}', datetime.now(tz=timezone.utc), None)
    cur = _cursor_returning(row)
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    result = store.get(_DID, _WS)
    assert result is not None
    assert result["discovery_id"] == _DID
    assert result["data"] == {"k": 1}


def test_get_wrong_workspace_returns_none() -> None:
    store, mock_pool = _make_store()
    cur = _cursor_returning(None)
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    result = store.get(_DID, workspace_id=2)
    assert result is None


def test_get_unknown_id_returns_none() -> None:
    store, mock_pool = _make_store()
    cur = _cursor_returning(None)
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    result = store.get("nonexistent", _WS)
    assert result is None


def test_put_upsert_is_idempotent() -> None:
    """put() must call execute exactly once — upsert handles conflict in DB."""
    store, mock_pool = _make_store()
    cur = MagicMock()
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    store.put(_DID, _WS, {"k": 1}, {"types": []}, 1)
    store.put(_DID, _WS, {"k": 2}, {"types": []}, 1)
    assert cur.execute.call_count == 2


def test_mark_confirmed_sets_status() -> None:
    store, mock_pool = _make_store()
    cur = MagicMock()
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    store.mark_confirmed(_DID, "job001")
    cur.execute.assert_called_once()
    call_args = cur.execute.call_args[0]
    assert _DID in call_args[1]


def test_update_confirm_state_persists_json() -> None:
    store, mock_pool = _make_store()
    cur = MagicMock()
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    state = {"completed_plans": ["a.csv"], "plan_run_ids": {"a.csv": "r1"}}
    store.update_confirm_state(_DID, state)
    cur.execute.assert_called_once()
    call_args = cur.execute.call_args[0]
    # First positional param should be JSON-serialised state
    assert json.loads(call_args[1][0]) == state


# ── pending_days logic ───────────────────────────────────────────────────────

def _list_row(status: str, created_at: datetime, confirmed_at=None):
    return ("did1", status, '{"types": []}', 5, created_at, confirmed_at)


def test_list_recent_pending_days_computed_for_pending() -> None:
    store, mock_pool = _make_store()
    created = datetime.now(tz=timezone.utc) - timedelta(days=9)
    cur = _cursor_returning([_list_row("pending", created)])
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    result = store.list_recent(_WS)
    assert len(result) == 1
    assert result[0]["pending_days"] == 9


def test_list_recent_pending_days_none_for_partial() -> None:
    store, mock_pool = _make_store()
    created = datetime.now(tz=timezone.utc) - timedelta(days=9)
    cur = _cursor_returning([_list_row("partial", created)])
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    result = store.list_recent(_WS)
    assert result[0]["pending_days"] is None


def test_list_recent_pending_days_none_for_confirmed() -> None:
    store, mock_pool = _make_store()
    created = datetime.now(tz=timezone.utc) - timedelta(days=9)
    confirmed = datetime.now(tz=timezone.utc)
    cur = _cursor_returning([_list_row("confirmed", created, confirmed)])
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    result = store.list_recent(_WS)
    assert result[0]["pending_days"] is None


def test_list_recent_pending_days_below_threshold() -> None:
    """pending_days is returned as-is; UI decides whether to show the warning."""
    store, mock_pool = _make_store()
    created = datetime.now(tz=timezone.utc) - timedelta(days=3)
    cur = _cursor_returning([_list_row("pending", created)])
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    result = store.list_recent(_WS)
    assert result[0]["pending_days"] == 3


def test_close_is_noop() -> None:
    store, _ = _make_store()
    store.close()  # must not raise


# ── Compression + oversized-payload guard ───────────────────────────────────
#
# data_json is gzip-compressed then base64-encoded (DiscoveryStore._serialize_
# data) -- keeps the column a plain JSON string on both Postgres and Oracle,
# no BYTEA/BLOB migration needed. Two real incidents motivate the size guard:
# a 32-file batch overran Postgres's wire-protocol message-length framing,
# and a 33-file batch hit Postgres's hard ~256MB JSONB-array limit. put()
# measures the size AFTER compression against discovery_max_payload_mb and
# rejects an oversized batch before ever calling execute().

import base64
import gzip
import os

from aryx.models import RawRecord, SourceRef
from aryx.store.discovery_store import (
    DiscoveryPayloadTooLarge,
    _deserialize_data,
    _serialize_data,
)


def _mention(name: str) -> RawRecord:
    return RawRecord(
        source=SourceRef(system="document", dataset="upload", record_id="doc:0"),
        payload={"type": "Entity", "name": name},
    )


class TestSerializeDeserializeRoundTrip:
    def test_result_is_base64_encoded_gzip_not_plain_json(self) -> None:
        data = {"mentions": [], "tabular": [], "summary": {}}
        serialized = _serialize_data(data)

        # The stored value is a JSON string (a quoted scalar) whose content,
        # once base64-decoded and gunzipped, is the real payload.
        b64 = json.loads(serialized)
        assert isinstance(b64, str)
        raw = gzip.decompress(base64.b64decode(b64))
        assert json.loads(raw)["tabular"] == []

    def test_raw_record_mentions_round_trip(self) -> None:
        data = {"mentions": [_mention("Acme Corp")], "tabular": [], "summary": {}}
        restored = _deserialize_data(_serialize_data(data))
        assert len(restored["mentions"]) == 1
        assert isinstance(restored["mentions"][0], RawRecord)
        assert restored["mentions"][0].payload["name"] == "Acme Corp"

    def test_tabular_plan_bytes_round_trip(self) -> None:
        raw_csv = b"id,name\n1,Widget\n2,Gadget\n"
        data = {
            "mentions": [], "summary": {},
            "tabular": [{"filename": "widgets.csv", "data": raw_csv,
                        "ontology_type": "Widget", "match_keys": ["id"]}],
        }
        restored = _deserialize_data(_serialize_data(data))
        assert restored["tabular"][0]["data"] == raw_csv

    def test_source_bytes_deduplicated_across_split_plans(self) -> None:
        """Regression test for the 2026-09-15 incident: an XML upload split
        into many tabular plans (one per detected entity type) previously
        base64-encoded and JSON-serialized the SAME original file's bytes
        once per plan. For a 240MB file split into 32 tables that meant
        ~7.7GB of duplicated base64 text built in memory before a single
        byte reached the database — the write never completed and the job
        sat frozen at 30% with no error. Each unique source_filename's bytes
        must now be encoded exactly once regardless of how many plans
        reference it, and every plan must still get its own correct bytes
        back after deserialize."""
        raw_source = b"<root>" + b"x" * 1000 + b"</root>"
        num_split_plans = 32
        data = {
            "mentions": [], "summary": {},
            "tabular": [
                {
                    "filename": f"table_{i}.csv", "data": f"id\n{i}\n".encode(),
                    "ontology_type": f"Type{i}", "match_keys": ["id"],
                    "source_filename": "big.xml", "source_bytes": raw_source,
                }
                for i in range(num_split_plans)
            ],
        }

        raw = gzip.decompress(base64.b64decode(json.loads(_serialize_data(data))))
        serialized = json.loads(raw)

        # The whole point: one encoded copy of the source file, not 32.
        assert list(serialized["_source_files_bytes"].keys()) == ["big.xml"]
        assert len(serialized["_source_files_bytes"]) == 1
        for plan in serialized["tabular"]:
            assert "source_bytes" not in plan
            assert plan["_source_bytes_ref"] == "big.xml"

        restored = _deserialize_data(_serialize_data(data))
        assert len(restored["tabular"]) == num_split_plans
        for i, plan in enumerate(restored["tabular"]):
            assert plan["source_bytes"] == raw_source
            assert plan["filename"] == f"table_{i}.csv"
            assert plan["data"] == f"id\n{i}\n".encode()
            assert "_source_bytes_ref" not in plan  # internal ref key doesn't leak out

    def test_source_bytes_deduplicated_across_two_distinct_source_files(self) -> None:
        """A batch containing plans from two different source XML/XLSX
        uploads must keep each source file's bytes separate — dedup is
        keyed by source_filename, not collapsed globally."""
        source_a = b"<a/>" * 50
        source_b = b"<b/>" * 80
        data = {
            "mentions": [], "summary": {},
            "tabular": [
                {"filename": "a1.csv", "data": b"x\n1\n", "ontology_type": "A",
                 "match_keys": ["x"], "source_filename": "a.xml", "source_bytes": source_a},
                {"filename": "a2.csv", "data": b"x\n2\n", "ontology_type": "A2",
                 "match_keys": ["x"], "source_filename": "a.xml", "source_bytes": source_a},
                {"filename": "b1.csv", "data": b"y\n3\n", "ontology_type": "B",
                 "match_keys": ["y"], "source_filename": "b.xml", "source_bytes": source_b},
            ],
        }

        restored = _deserialize_data(_serialize_data(data))
        by_filename = {p["filename"]: p for p in restored["tabular"]}
        assert by_filename["a1.csv"]["source_bytes"] == source_a
        assert by_filename["a2.csv"]["source_bytes"] == source_a
        assert by_filename["b1.csv"]["source_bytes"] == source_b

    def test_plan_without_source_bytes_is_unaffected(self) -> None:
        """A plain CSV upload (no xlsx/xml source_bytes) must round-trip
        without the optional dedup fields ever being introduced."""
        data = {
            "mentions": [], "summary": {},
            "tabular": [{"filename": "x.csv", "data": b"a,b\n1,2\n",
                        "ontology_type": "X", "match_keys": ["a"]}],
        }
        restored = _deserialize_data(_serialize_data(data))
        assert "_source_files_bytes" not in restored
        assert "source_bytes" not in restored["tabular"][0]

    def test_legacy_uncompressed_json_still_reads(self) -> None:
        """A plain JSON dict (not base64/gzip-wrapped) must still deserialize
        -- covers rows written before this encoding existed, and the "{}"
        empty-row fallback used elsewhere in this module."""
        assert _deserialize_data('{"k": 1}') == {"k": 1}
        assert _deserialize_data("{}") == {}


class TestOversizedPayloadGuard:
    def test_rejects_payload_over_the_configured_limit(self) -> None:
        store, mock_pool = _make_store()
        cur = MagicMock()
        conn = _conn_with_cursor(cur)
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        # Incompressible random bytes -- gzip can't shrink this away, so a
        # 2MB payload reliably exceeds a 1MB cap after compression.
        oversized = base64.b64encode(os.urandom(2 * 1024 * 1024)).decode("ascii")
        data = {"mentions": [], "summary": {},
                "tabular": [{"filename": "big.csv", "data": oversized}]}

        with patch("aryx.store.discovery_store.get_settings") as mock_cfg:
            mock_cfg.return_value.discovery_max_payload_mb = 1
            with pytest.raises(DiscoveryPayloadTooLarge):
                store.put(_DID, _WS, data, {}, 1)

        cur.execute.assert_not_called()

    def test_allows_payload_at_or_under_the_configured_limit(self) -> None:
        store, mock_pool = _make_store()
        cur = MagicMock()
        conn = _conn_with_cursor(cur)
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        data = {"mentions": [], "summary": {},
                "tabular": [{"filename": "small.csv", "data": "id,name\n1,Widget\n"}]}

        with patch("aryx.store.discovery_store.get_settings") as mock_cfg:
            mock_cfg.return_value.discovery_max_payload_mb = 300
            store.put(_DID, _WS, data, {}, 1)

        cur.execute.assert_called_once()

    def test_compressible_payload_over_raw_size_but_under_compressed_limit_succeeds(self) -> None:
        """The actual incident this closes: a highly-compressible (CSV-like)
        payload whose raw size alone would look oversized must succeed,
        because the guard measures the compressed size."""
        store, mock_pool = _make_store()
        cur = MagicMock()
        conn = _conn_with_cursor(cur)
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        compressible = ("id,name,value\n1,Widget,100\n") * 200_000  # ~5MB raw
        data = {"mentions": [], "summary": {},
                "tabular": [{"filename": "big.csv", "data": compressible}]}

        with patch("aryx.store.discovery_store.get_settings") as mock_cfg:
            mock_cfg.return_value.discovery_max_payload_mb = 2
            store.put(_DID, _WS, data, {}, 1)

        cur.execute.assert_called_once()
