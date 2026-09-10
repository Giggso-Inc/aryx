"""Shared helpers for the Oracle Property Graph writer: attr sanitization,
chunking, and display-name extraction.

Split out of `graph/oracle_graph_store.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

import json
from typing import Any

_NAME_KEYS = ("name", "full_name", "title", "label", "ticket_ref", "ref",
              "sku", "code", "email", "username", "_text")

# Oracle ADB thin-client ORA-03106 guard values.
#
# _CHUNK_MAX_BYTES is the real safety net against ORA-03106 (oversized
# payload, e.g. CPQ function bodies in attrs) -- it already caps accumulated
# bind-value bytes per executemany() call regardless of row count.
#
# _CHUNK_MAX_ROWS was previously 25, sized to keep bind-slot count low as a
# rough proxy for packet size. In practice that made the ROW cap the binding
# constraint almost always (25 rows of typical attrs is nowhere near 50KB),
# turning every write into far more round-trips to Oracle Cloud than the byte
# budget actually required -- measured live on a 60,144-relationship batch:
# 2,406 round-trips at ~0.26s each = ~10.5 min, for a stage that should take
# well under a minute (see docs/SCALABILITY_BOTTLENECKS.md). Raised so the
# byte cap -- not the row cap -- is what decides when to split a batch.
_CHUNK_MAX_ROWS = 500
_CHUNK_MAX_BYTES = 50_000

# Graph projection attrs — display + traversal only, not source of truth.
# Full attribute text lives in aryx_entity.attributes (the primary store).
_GRAPH_ATTR_STR_MAX = 200


def _safe_attrs_json(attrs: dict[str, Any]) -> str:
    """Serialize attrs, always truncating long string values to _GRAPH_ATTR_STR_MAX chars.

    The graph store is a projection cache — full text lives in aryx_entity.attributes.
    CPQ function bodies and scripts cause ORA-03106 even across small row counts
    because each bind variable contributes to the wire-protocol packet size.
    Trim unconditionally so no single bind value is large.
    """
    trimmed = {
        k: (v[:_GRAPH_ATTR_STR_MAX] + "…" if isinstance(v, str) and len(v) > _GRAPH_ATTR_STR_MAX else v)
        for k, v in attrs.items()
    }
    return json.dumps(trimmed, default=str)


def _iter_chunks(batch: list[dict], payload_key: str = "attrs") -> list[list[dict]]:
    """Yield sub-lists bounded by row count AND estimated payload bytes.

    Prevents ORA-03106 when individual attribute JSON blobs are large
    (e.g. CPQ function bodies) even at low row counts.
    """
    chunk: list[dict] = []
    size = 0
    for row in batch:
        val = row.get(payload_key)
        row_bytes = len(val) if isinstance(val, (str, bytes)) else 0
        if chunk and (len(chunk) >= _CHUNK_MAX_ROWS or size + row_bytes > _CHUNK_MAX_BYTES):
            yield chunk
            chunk = []
            size = 0
        chunk.append(row)
        size += row_bytes
    if chunk:
        yield chunk


def _display_name(attributes: dict[str, Any]) -> str:
    """Extract a human-readable display name from entity attributes."""
    for key in _NAME_KEYS:
        value = attributes.get(key)
        if value:
            return str(value)
    for key, value in attributes.items():
        if key.startswith("_"):
            continue
        if isinstance(value, str) and 0 < len(value) <= 80:
            return value
    return ""
