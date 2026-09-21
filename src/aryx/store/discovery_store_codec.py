"""Custom JSON codec for discovery data (gzip + base64, bytes/Pydantic-aware).

Split out of `store/discovery_store.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Calls neither `load`/`get_pool`/`get_settings` —
zero patch risk, confirmed via grep.
"""
from __future__ import annotations

import base64
import gzip
import json
from datetime import datetime
from typing import Any


class DiscoveryPayloadTooLarge(ValueError):
    """Raised when a discovery result is too large to persist in one write.

    Two real, confirmed incidents motivate this guard:
    - A 32-file BigMachines CSV catalog batch's serialized payload was large
      enough to overrun Postgres's wire-protocol fixed-size message-length
      framing, killing the connection outright with "invalid message
      length" instead of a normal query error.
    - A 33-file SL3500e batch separately hit a second, harder wall: a naive
      uncompressed JSON payload can exceed engine-level size limits (Postgres
      caps a single JSONB array's serialized size at 268,435,455 bytes).

    ``data_json`` is stored gzip-compressed then base64-encoded — this keeps
    it a plain JSON string (no column-type/migration change, works
    unchanged on both Postgres and Oracle ADB 23ai) while shrinking
    text-heavy CSV/mention payloads substantially. This guard measures the
    size AFTER compression against ``settings.discovery_max_payload_mb``, so
    an oversized batch still fails as a clean, catchable error instead of
    crashing the connection or failing deep inside a database write.
    """

_COLUMNS = [
    "discovery_id", "workspace_id", "status",
    "data_json", "summary_json", "file_count",
    "confirm_state", "created_at", "confirmed_at",
]

# ── Custom JSON codec for discovery data ─────────────────────────────────────
# data["tabular"][i]["data"] is bytes (raw CSV/JSON file content).
# data["mentions"] is a list of RawRecord Pydantic models.
# Standard json.dumps cannot handle either; these helpers do a lossless
# round-trip so the confirm step receives the same objects it would have
# gotten from the original in-memory dict.

class _DiscoveryEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, bytes):
            return {"__b64__": base64.b64encode(obj).decode("ascii")}
        # Pydantic v2 BaseModel — detected by duck-typing to avoid a hard import
        if hasattr(obj, "model_dump") and hasattr(obj, "__class__"):
            return {
                "__pydantic__": type(obj).__qualname__,
                "__module__": type(obj).__module__,
                "v": obj.model_dump(mode="json"),
            }
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def _discovery_hook(d: dict) -> Any:
    if "__b64__" in d and len(d) == 1:
        return base64.b64decode(d["__b64__"])
    if "__pydantic__" in d:
        cls_name: str = d["__pydantic__"]
        module: str = d.get("__module__", "")
        v: dict = d.get("v", {})
        try:
            import importlib  # noqa: PLC0415
            mod = importlib.import_module(module)
            cls = getattr(mod, cls_name.split(".")[-1])
            return cls.model_validate(v)
        except Exception:  # noqa: BLE001
            return v  # fall back to plain dict if class no longer exists
    return d


def _dedupe_tabular_source_bytes(data: dict) -> dict:
    """Deduplicate each source file's bytes across split-table plans.

    An XML/XLSX upload is split into one tabular plan per detected entity
    type (doc_discovery.read_files's converted_tabular), and every one of
    those plans carries its own `source_bytes` reference to the SAME
    original file so downstream code (doc_discovery._persist_tabular_sources)
    can regroup them by source_filename at confirm time. Encoding
    source_bytes independently per plan used to base64+JSON-serialize the
    same multi-hundred-MB source file once per split table (32x for a
    32-entity-type XML) -- for a 240MB upload that meant ~7.7GB of
    duplicated base64 text built in memory before a single byte reached
    the database, which silently stalled the write with no exception
    (incident 2026-09-15, discovery 0206aacbfc4c4de897e507cdc86724a0).

    Each unique source_filename's bytes are pulled out exactly once into a
    top-level `_source_files_bytes` map (left as raw `bytes` objects --
    `_DiscoveryEncoder.default()` already base64-encodes any `bytes` value
    generically, so this doesn't need its own manual encoding step); every
    plan referencing that file keeps only a `_source_bytes_ref` key instead
    of its own copy.
    """
    if "tabular" not in data:
        return data
    out = dict(data)
    source_bytes_by_file: dict[str, bytes] = {}
    tabular_out = []
    for p in out["tabular"]:
        plan = dict(p)
        src_name = plan.get("source_filename")
        src_bytes = plan.get("source_bytes")
        if src_name is not None and isinstance(src_bytes, (bytes, bytearray)):
            if src_name not in source_bytes_by_file:
                source_bytes_by_file[src_name] = bytes(src_bytes)
            plan.pop("source_bytes")
            plan["_source_bytes_ref"] = src_name
        tabular_out.append(plan)
    out["tabular"] = tabular_out
    if source_bytes_by_file:
        out["_source_files_bytes"] = source_bytes_by_file
    return out


def _rehydrate_tabular_source_bytes(data: dict) -> dict:
    """Inverse of `_dedupe_tabular_source_bytes` — restores each plan's
    `source_bytes` from the shared dedup map. A no-op for data with no
    `_source_files_bytes` map (plain CSV/JSON uploads, or rows written
    before this dedup existed)."""
    if "_source_files_bytes" not in data:
        return data
    out = dict(data)
    source_files_bytes = out.pop("_source_files_bytes")
    tabular_out = []
    for p in out.get("tabular", []):
        plan = dict(p)
        ref = plan.pop("_source_bytes_ref", None)
        if ref is not None:
            plan["source_bytes"] = source_files_bytes[ref]
        tabular_out.append(plan)
    out["tabular"] = tabular_out
    return out


def _serialize_data(data: dict) -> str:
    """Return data_json's column value: gzip-compressed JSON, base64-encoded.

    The result is JSON-encoded again (a quoted string) so the column keeps
    holding valid JSON on both backends — no BYTEA/BLOB column or migration
    needed, just a different encoding of the same text column.
    """
    data = _dedupe_tabular_source_bytes(data)
    raw = json.dumps(data, cls=_DiscoveryEncoder).encode("utf-8")
    compressed = gzip.compress(raw)
    return json.dumps(base64.b64encode(compressed).decode("ascii"))


def _deserialize_data(s: str) -> dict:
    parsed = json.loads(s)
    if not isinstance(parsed, str):
        # Empty-row fallback ("{}" default) — not a base64 payload.
        return parsed if isinstance(parsed, dict) else {}
    compressed = base64.b64decode(parsed)
    raw = gzip.decompress(compressed)
    data = json.loads(raw, object_hook=_discovery_hook)
    return _rehydrate_tabular_source_bytes(data)


def _row_to_dict(values: tuple) -> dict[str, Any]:
    row = dict(zip(_COLUMNS, values))
    row["data"]          = _deserialize_data(row.pop("data_json") or "{}")
    row["summary"]       = json.loads(row.pop("summary_json") or "{}")
    row["confirm_state"] = json.loads(row.pop("confirm_state") or "{}")
    return row
