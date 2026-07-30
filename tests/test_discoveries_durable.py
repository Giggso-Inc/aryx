"""Tests for the Postgres-backed discoveries store (Raven review, PR #120).

Real finding: discoveries.put()/get() were a plain in-process dict —
process memory only, per the old module's own docstring. The read job's
progress callback genuinely flushed a growing partial snapshot on every N
chunks, but a crash or restart partway through a long document still wiped
every mention extracted so far, because nothing was ever written to disk.
Fix: back the store with Postgres (aryx_discovery, migration 0035) so a
restart resumes from the last flush instead of losing everything.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.discoveries import (
    DiscoveryPayloadTooLarge,
    _deserialize,
    _serialize,
    drop,
    get,
    put,
)
from aryx.models import RawRecord, SourceRef


def _mention(name: str, chunk_index: int = 0) -> RawRecord:
    return RawRecord(
        source=SourceRef(system="document", dataset="upload", record_id=f"doc:{chunk_index}"),
        payload={"type": "Entity", "name": name, "chunk_index": chunk_index},
    )


# ---------------------------------------------------------------------------
# Serialization round-trip — the part most likely to silently corrupt data,
# since RawRecord (a pydantic model) and raw file bytes aren't natively
# JSON-serialisable.
# ---------------------------------------------------------------------------

class TestSerializationRoundTrip:
    def test_raw_record_mentions_round_trip(self):
        original = [_mention("Acme Corp"), _mention("Globex", chunk_index=5)]
        data = {"mentions": original, "tabular": [], "summary": {}, "workspace_id": 7}

        serialized = _serialize(data)
        # Must be plain JSON-safe types now (no RawRecord/bytes objects).
        assert isinstance(serialized["mentions"][0], dict)

        restored = _deserialize(serialized)
        assert len(restored["mentions"]) == 2
        assert all(isinstance(m, RawRecord) for m in restored["mentions"])
        assert restored["mentions"][0].payload["name"] == "Acme Corp"
        assert restored["mentions"][1].payload["chunk_index"] == 5

    def test_tabular_plan_bytes_round_trip(self):
        """Tabular plans carry raw CSV bytes (and XML/XLSX source_bytes) —
        both must survive serialize -> deserialize byte-for-byte."""
        raw_csv = b"id,name\n1,Widget\n2,Gadget\n"
        raw_source = b"<root><item id='1'/></root>"
        data = {
            "mentions": [],
            "tabular": [{
                "filename": "widgets.csv", "data": raw_csv,
                "ontology_type": "Widget", "match_keys": ["id"],
                "source_filename": "widgets.xml", "source_bytes": raw_source,
            }],
            "summary": {}, "workspace_id": 3,
        }

        serialized = _serialize(data)
        assert isinstance(serialized["tabular"][0]["data"], str)  # base64 text now
        assert isinstance(serialized["tabular"][0]["source_bytes"], str)

        restored = _deserialize(serialized)
        plan = restored["tabular"][0]
        assert plan["data"] == raw_csv
        assert plan["source_bytes"] == raw_source
        assert plan["ontology_type"] == "Widget"  # untouched fields pass through

    def test_plan_without_source_bytes_is_unaffected(self):
        """A plain CSV upload (no xlsx/xml source_bytes) must round-trip
        without the optional fields ever being introduced."""
        data = {
            "mentions": [],
            "tabular": [{"filename": "x.csv", "data": b"a,b\n1,2\n",
                        "ontology_type": "X", "match_keys": ["a"]}],
            "summary": {}, "workspace_id": 1,
        }
        restored = _deserialize(_serialize(data))
        plan = restored["tabular"][0]
        assert plan["data"] == b"a,b\n1,2\n"
        assert "source_bytes" not in plan

    def test_partial_snapshot_shape_round_trips(self):
        """The exact partial shape written by the progress callback —
        summary/types present, tabular empty, partial=True — must survive."""
        data = {
            "mentions": [_mention("Acme Corp")],
            "tabular": [],
            "summary": {"types": [{"type": "Entity", "count": 1, "examples": ["Acme Corp"]}],
                        "files": []},
            "workspace_id": 12,
            "partial": True,
        }
        restored = _deserialize(_serialize(data))
        assert restored["partial"] is True
        assert restored["summary"]["types"][0]["type"] == "Entity"
        assert restored["mentions"][0].payload["name"] == "Acme Corp"


# ---------------------------------------------------------------------------
# put()/get()/drop() — mocked pool, verifying the right SQL + params fire.
# ---------------------------------------------------------------------------

def _mock_pool(fetchone_return=None, rowcount=0):
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = fetchone_return
    mock_cur.rowcount = rowcount
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_pool = MagicMock()
    mock_pool.connection.return_value.__enter__.return_value = mock_conn
    return mock_pool, mock_cur


class TestPutGetDrop:
    def test_put_upserts_with_workspace_id_from_payload(self):
        mock_pool, mock_cur = _mock_pool()
        data = {"mentions": [], "tabular": [], "summary": {}, "workspace_id": 42}
        with patch("aryx.discoveries.get_pool", return_value=mock_pool), \
             patch("aryx.discoveries.get_settings") as mock_cfg:
            mock_cfg.return_value.rdb_dsn = "postgresql://test"
            mock_cfg.return_value.discovery_max_payload_mb = 300
            put("did-123", data)

        sql, params = mock_cur.execute.call_args[0]
        assert "aryx_discovery" in sql
        assert params[0] == "did-123"
        assert params[1] == 42

    def test_put_defaults_workspace_id_to_one_when_absent(self):
        mock_pool, mock_cur = _mock_pool()
        data = {"mentions": [], "tabular": [], "summary": {}}
        with patch("aryx.discoveries.get_pool", return_value=mock_pool), \
             patch("aryx.discoveries.get_settings") as mock_cfg:
            mock_cfg.return_value.rdb_dsn = "postgresql://test"
            mock_cfg.return_value.discovery_max_payload_mb = 300
            put("did-456", data)

        _, params = mock_cur.execute.call_args[0]
        assert params[1] == 1

    def test_get_returns_none_for_unknown_discovery(self):
        mock_pool, _ = _mock_pool(fetchone_return=None)
        with patch("aryx.discoveries.get_pool", return_value=mock_pool), \
             patch("aryx.discoveries.get_settings") as mock_cfg:
            mock_cfg.return_value.rdb_dsn = "postgresql://test"
            result = get("does-not-exist")

        assert result is None

    def test_get_deserializes_stored_row(self):
        stored_json = {"mentions": [{"source": {"system": "document", "dataset": "upload",
                                                 "record_id": "doc:0"},
                                     "payload": {"type": "Entity", "name": "Acme Corp"},
                                     "extracted_at": "2026-01-01T00:00:00Z"}],
                      "tabular": [], "summary": {}, "workspace_id": 5}
        mock_pool, _ = _mock_pool(fetchone_return=(stored_json,))
        with patch("aryx.discoveries.get_pool", return_value=mock_pool), \
             patch("aryx.discoveries.get_settings") as mock_cfg:
            mock_cfg.return_value.rdb_dsn = "postgresql://test"
            result = get("did-789")

        assert result is not None
        assert isinstance(result["mentions"][0], RawRecord)
        assert result["mentions"][0].payload["name"] == "Acme Corp"

    def test_drop_deletes_by_discovery_id(self):
        mock_pool, mock_cur = _mock_pool(rowcount=1)
        with patch("aryx.discoveries.get_pool", return_value=mock_pool), \
             patch("aryx.discoveries.get_settings") as mock_cfg:
            mock_cfg.return_value.rdb_dsn = "postgresql://test"
            drop("did-123")

        sql, params = mock_cur.execute.call_args[0]
        assert "aryx_discovery" in sql
        assert params == ("did-123",)


# ---------------------------------------------------------------------------
# Oversized-payload guard (RCA 2026-07-30): discoveries.put() writes an
# entire multi-file discovery result as ONE JSONB value in ONE INSERT
# parameter. A 32-file BigMachines/Oracle CPQ CSV catalog batch grew large
# enough in one combined write to overrun Postgres's wire-protocol
# message-length framing -- confirmed live via aryx-postgres-1's own log:
# "LOG: invalid message length" -- killing that connection outright
# (psycopg.OperationalError: server closed the connection unexpectedly)
# rather than failing as a normal, catchable query error. put() now
# computes the real serialized size and rejects anything over
# settings.discovery_max_payload_mb BEFORE attempting the write, so an
# oversized batch fails cleanly (caught by doc_discover_api._read_job's
# existing except block, surfaced as a normal "failed" job status) instead
# of crashing the connection.
# ---------------------------------------------------------------------------

class TestOversizedPayloadGuard:
    def test_put_rejects_payload_over_the_configured_limit(self):
        """A payload whose serialized size exceeds discovery_max_payload_mb
        must raise DiscoveryPayloadTooLarge and never reach the DB -- this
        is the exact failure mode from the live incident, reproduced
        deterministically with a small limit instead of a multi-hundred-MB
        real catalog batch."""
        mock_pool, mock_cur = _mock_pool()
        # ~2MB of raw bytes in one tabular plan is enough to exceed a 1MB cap.
        oversized_csv = b"x" * (2 * 1024 * 1024)
        data = {
            "mentions": [], "workspace_id": 9,
            "tabular": [{"filename": "big.csv", "data": oversized_csv,
                        "ontology_type": "Big", "match_keys": ["id"]}],
            "summary": {},
        }
        with patch("aryx.discoveries.get_pool", return_value=mock_pool), \
             patch("aryx.discoveries.get_settings") as mock_cfg:
            mock_cfg.return_value.rdb_dsn = "postgresql://test"
            mock_cfg.return_value.discovery_max_payload_mb = 1
            try:
                put("did-oversized", data)
                assert False, "expected DiscoveryPayloadTooLarge to be raised"
            except DiscoveryPayloadTooLarge as exc:
                assert "1 MB" in str(exc) or "1MB" in str(exc).replace(" ", "")

        # The write must never have been attempted -- rejecting BEFORE the
        # execute() call is the entire point (avoid the protocol-level kill).
        mock_cur.execute.assert_not_called()

    def test_put_allows_payload_at_or_under_the_configured_limit(self):
        """A normal-sized discovery result must be unaffected -- the guard
        must not false-positive on everyday small batches."""
        mock_pool, mock_cur = _mock_pool()
        small_csv = b"id,name\n1,Widget\n"
        data = {
            "mentions": [], "workspace_id": 9,
            "tabular": [{"filename": "small.csv", "data": small_csv,
                        "ontology_type": "Small", "match_keys": ["id"]}],
            "summary": {},
        }
        with patch("aryx.discoveries.get_pool", return_value=mock_pool), \
             patch("aryx.discoveries.get_settings") as mock_cfg:
            mock_cfg.return_value.rdb_dsn = "postgresql://test"
            mock_cfg.return_value.discovery_max_payload_mb = 300
            put("did-small", data)

        mock_cur.execute.assert_called_once()

    def test_put_error_message_reports_actual_and_limit_size(self):
        """The rejection error must be self-explanatory -- actionable
        without needing to read the source, since it surfaces straight to
        the job's user-facing error field (doc_discover_api._read_job)."""
        mock_pool, _ = _mock_pool()
        oversized_csv = b"x" * (3 * 1024 * 1024)
        data = {
            "mentions": [], "workspace_id": 1,
            "tabular": [{"filename": "big.csv", "data": oversized_csv,
                        "ontology_type": "Big", "match_keys": ["id"]}],
            "summary": {},
        }
        with patch("aryx.discoveries.get_pool", return_value=mock_pool), \
             patch("aryx.discoveries.get_settings") as mock_cfg:
            mock_cfg.return_value.rdb_dsn = "postgresql://test"
            mock_cfg.return_value.discovery_max_payload_mb = 1
            try:
                put("did-msg", data)
                assert False, "expected DiscoveryPayloadTooLarge to be raised"
            except DiscoveryPayloadTooLarge as exc:
                msg = str(exc)
                assert "ARYX_DISCOVERY_MAX_PAYLOAD_MB" in msg
                assert "MB" in msg
