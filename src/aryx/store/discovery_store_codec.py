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


def _serialize_data(data: dict) -> str:
    """Return data_json's column value: gzip-compressed JSON, base64-encoded.

    The result is JSON-encoded again (a quoted string) so the column keeps
    holding valid JSON on both backends — no BYTEA/BLOB column or migration
    needed, just a different encoding of the same text column.
    """
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
    return json.loads(raw, object_hook=_discovery_hook)


def _row_to_dict(values: tuple) -> dict[str, Any]:
    row = dict(zip(_COLUMNS, values))
    row["data"]          = _deserialize_data(row.pop("data_json") or "{}")
    row["summary"]       = json.loads(row.pop("summary_json") or "{}")
    row["confirm_state"] = json.loads(row.pop("confirm_state") or "{}")
    return row
