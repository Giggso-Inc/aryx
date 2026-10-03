"""CSV multi-part name-column consolidation for tabular uploads.

Split out of `pipeline/doc_discovery.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03).
"""
from __future__ import annotations

import csv
import io
import logging
import re

from aryx.raven_log import raven_log

logger = logging.getLogger(__name__)


def _consolidate_csv_names(data: bytes, did: str | None = None) -> bytes:
    """Merge multi-part name columns into a single ``name`` field.

    Handles patterns like COMPANY_NAME / COMPANY_NAME_2 … COMPANY_NAME_5
    produced by government/defense data exports where a long name is split
    across several continuation columns.  The first part column becomes
    ``name``; continuation parts are appended (space-separated) then dropped.
    """
    try:
        text = data.decode("utf-8", "ignore")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raven_log("DEBUG", "P4", "ingest.csv.consolidate empty file, unchanged",
                      context={"discovery_id": did, "selected_option": "unchanged", "reason_code": "NO_HEADER"})
            return data
        headers = list(reader.fieldnames)

        # Find multi-part name groups: columns whose names differ only by a
        # trailing _2 / _3 / _4 / _5 suffix (e.g. COMPANY_NAME, COMPANY_NAME_2).
        base_names: dict[str, list[str]] = {}
        for h in headers:
            m = re.match(r"^(.+?)(?:_[2-9]|_\d{2,})$", h)
            if m:
                base = m.group(1)
                if base in headers:
                    base_names.setdefault(base, []).append(h)

        if not base_names:
            raven_log("DEBUG", "P4", "ingest.csv.consolidate no multi-part name columns",
                      context={"discovery_id": did, "columns": len(headers), "selected_option": "unchanged",
                               "available_options": ["merge", "unchanged"], "reason_code": "NO_NAME_GROUPS"})
            return data

        rows = list(reader)
        out_headers = [h for h in headers if not any(h in parts for parts in base_names.values())]
        if "name" not in [h.lower() for h in out_headers]:
            # Insert 'name' right after the base column
            for base in base_names:
                if base in out_headers:
                    idx = out_headers.index(base)
                    out_headers.insert(idx + 1, "name")
                    break

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=out_headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            for base, continuations in base_names.items():
                parts = [row.get(base, "").strip()]
                for cont in continuations:
                    v = row.get(cont, "").strip()
                    if v:
                        parts.append(v)
                full = " ".join(p for p in parts if p)
                row[base] = full
                # Also set 'name' if not already present in this row
                if "name" not in row or not row["name"]:
                    row["name"] = full
            writer.writerow(row)
        logger.info("consolidate_csv_names did=%s merged_groups=%d columns=%s rows=%d",
                    did, len(base_names), list(base_names.keys()), len(rows))
        raven_log("DEBUG", "P4", "ingest.csv.consolidate multi-part name columns merged",
                  context={"discovery_id": did, "merged_groups": len(base_names), "group_columns": list(base_names.keys()),
                           "rows": len(rows), "selected_option": "merge", "available_options": ["merge", "unchanged"],
                           "reason_code": "NAME_GROUPS_FOUND"})
        return buf.getvalue().encode("utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("consolidate_csv_names did=%s failed, returning original data unmodified: %s",
                        did, exc)
        raven_log("WARN", "P3", "ingest.csv.consolidate failed, original data kept",
                  error_code="ARYX_ING_CSV_CONSOLIDATE_FAILED",
                  context={"discovery_id": did, "triggering_error": type(exc).__name__,
                           "recovery_selected": "return_original", "exit_condition": "degraded", "result": "degraded"})
        return data
