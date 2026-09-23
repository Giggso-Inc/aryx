"""Oracle-only guard: keep one datasource catalog config under Oracle's
native JSON object size cap.

Split out of `source_catalog_upsert.py` (same Raven Style Compliance Plan
pattern as the rest of `source_catalog_*` -- zero patch risk, confirmed
via grep).

Oracle Database's native `JSON` column type has a hard, documented maximum
object size of 32MB (Oracle Database 23ai JSON Developer's Guide). Real
incident 2026-09-22: a 32-entity-type XML upload's `config_json` write
failed with `ORA-40604: exceeded maximum size for a JSON data type object`
/ `JZN-00092: JSON too large for binary encoding`.

`_MAX_INLINE_CONTENT_BYTES` in `source_catalog_upsert.py` guards each
individual file's `content_b64` against Postgres's *per-scalar* jsonb
string limit (268,435,455 bytes) -- Postgres has no equivalent
*whole-document* cap, so a config whose every single asset is comfortably
under that per-file limit can still add up to hundreds of MB there once
combined (this XML upload's 32 generated per-type CSV assets each sat well
under 170MiB alone). Oracle's 32MB limit is a whole-object cap, so the
per-file guard alone doesn't catch this on Oracle: `apply_oracle_json_
budget` sums every embedded `content_b64` across one catalog entry (the
source file's own entry, plus every item in `generated_assets`) and, only
when running on the Oracle backend, strips the largest entries' content
first until the total fits -- marking each stripped entry
`content_omitted_oversized=True`, the same marker `_safe_content_fields`
already sets for its own per-file cap. Every read site already has a
documented fallback for that marker (see `_safe_content_fields`'s
docstring in `source_catalog_upsert.py`), so this degrades
original-file/asset download and preview for the stripped entries instead
of failing the whole confirm job.
"""
from __future__ import annotations

import time
from typing import Any

from aryx.raven_log import new_span_id, new_trace_id, raven_log
from aryx.source.source_catalog_meta import _CATALOG_KEY

# Budget well under Oracle's documented 32MB cap to leave headroom for the
# rest of the document's keys/metadata on top of the embedded content.
_MAX_ORACLE_JSON_OBJECT_BYTES = 28 * 1024 * 1024


def _content_entries(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Every dict in `config` carrying its own `content_b64` field: the
    source file's own entry, plus each item in `generated_assets`."""
    entries: list[dict[str, Any]] = []
    catalog = config.get(_CATALOG_KEY, {})
    for meta in catalog.values():
        if not isinstance(meta, dict):
            continue
        if "content_b64" in meta:
            entries.append(meta)
        for asset in meta.get("generated_assets") or []:
            if isinstance(asset, dict) and "content_b64" in asset:
                entries.append(asset)
    return entries


def _source_filename(config: dict[str, Any]) -> str:
    for meta in config.get(_CATALOG_KEY, {}).values():
        if isinstance(meta, dict) and meta.get("source_filename"):
            return str(meta["source_filename"])
    return "unknown"


def apply_oracle_json_budget(config: dict[str, Any]) -> dict[str, Any]:
    """Strip `content_b64` from the largest entries (in place) until
    `config`'s total embedded-content size fits under Oracle's native JSON
    object cap. No-op on Postgres and no-op when already under budget."""
    from aryx.config import get_settings  # noqa: PLC0415

    if get_settings().effective_db_backend() != "oci":
        return config
    entries = [e for e in _content_entries(config) if e.get("content_b64")]
    total = sum(len(e["content_b64"]) for e in entries)
    if total <= _MAX_ORACLE_JSON_OBJECT_BYTES:
        return config
    started = time.monotonic()
    stripped_bytes: list[int] = []
    for entry in sorted(entries, key=lambda e: len(e["content_b64"]), reverse=True):
        removed = len(entry["content_b64"])
        entry["content_b64"] = None
        entry["content_omitted_oversized"] = True
        stripped_bytes.append(removed)
        total -= removed
        if total <= _MAX_ORACLE_JSON_OBJECT_BYTES:
            break
    raven_log(
        level="WARN", criticality="P3",
        message="Oracle JSON budget exceeded: stripped content_b64 from oversized catalog entries",
        error_code="ORACLE_JSON_BUDGET_STRIPPED",
        trace_id=new_trace_id(), span_id=new_span_id(),
        context={
            "task_id": _source_filename(config),
            "final_status": "stripped",
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
            "stage": "oracle_json_budget",
            "result": "content_stripped",
            "reason_code": "ORACLE_JSON_BUDGET_EXCEEDED",
            "impact_scope": "catalog_entries",
            "entries_stripped": len(stripped_bytes),
            "bytes_freed": sum(stripped_bytes),
            "final_total_bytes": total,
        },
    )
    return config
