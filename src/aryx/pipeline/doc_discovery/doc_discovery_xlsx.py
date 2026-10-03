"""Parse an Excel workbook into one CSV per worksheet.

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

# Non-alphanumeric run -> single underscore, for turning an arbitrary sheet
# title into a filesystem/dataset-key-safe slug ("Order Items!" -> "Order_Items").
_SHEET_SLUG_RE = re.compile(r"[^A-Za-z0-9]+")


def _sheet_slug(title: str) -> str:
    slug = _SHEET_SLUG_RE.sub("_", title or "").strip("_")
    return slug or "Sheet"


def _xlsx_to_csvs(data: bytes, stem: str, log_id: str | None = None) -> list[tuple[bytes, str]]:
    """Parse an Excel workbook -> one CSV per worksheet, each an independent dataset.

    Mirrors _xml_to_csvs' shape (one source file -> N tabular CSV byte-strings
    + names), so the caller wires xlsx sheets into the exact same per-file
    run_pipeline() loop, FK-detection, and traceability machinery already
    used for multi-entity XML uploads — no parallel ingestion path needed.

    Naming: "{workbook_stem}__{sheet_slug}.csv" — the shared stem prefix is
    what "maintains the association with the parent workbook" (a query for
    datasets starting with "{stem}__" recovers every sheet from one upload),
    while the sheet_slug suffix keeps each sheet's dataset key unique.

    Skips (never silently ingested as garbage datasets):
    - hidden/very-hidden sheets (ws.sheet_state != "visible")
    - sheets with no header row at all (completely empty)
    - sheets with a header but zero data rows (header-only / template tabs,
      e.g. a blank "Template" tab shipped alongside real data tabs)
    """
    from openpyxl import load_workbook

    prefix = f"[{log_id}] " if log_id else ""
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        results: list[tuple[bytes, str]] = []
        for ws in wb.worksheets:
            if ws.sheet_state != "visible":
                logger.info("%sxlsx_to_csvs stem=%s: skipping hidden sheet %r",
                           prefix, stem, ws.title)
                raven_log("DEBUG", "P4", "ingest.xlsx.sheet skipped hidden",
                          context={"log_id": log_id, "stem": stem, "sheet": ws.title, "sheet_state": str(ws.sheet_state),
                                   "decision": "skip", "reason_code": "HIDDEN_SHEET"})
                continue
            rows_iter = ws.iter_rows(values_only=True)
            try:
                header_row = next(rows_iter)
            except StopIteration:
                logger.info("%sxlsx_to_csvs stem=%s: skipping empty sheet %r",
                           prefix, stem, ws.title)
                raven_log("DEBUG", "P4", "ingest.xlsx.sheet skipped empty",
                          context={"log_id": log_id, "stem": stem, "sheet": ws.title, "decision": "skip",
                                   "reason_code": "EMPTY_SHEET"})
                continue
            header = [str(h).strip() if h is not None else "" for h in header_row]
            if not any(header):
                logger.info("%sxlsx_to_csvs stem=%s: skipping sheet %r with no header",
                           prefix, stem, ws.title)
                raven_log("DEBUG", "P4", "ingest.xlsx.sheet skipped no header",
                          context={"log_id": log_id, "stem": stem, "sheet": ws.title, "decision": "skip",
                                   "reason_code": "NO_HEADER"})
                continue

            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(header)
            row_count = 0
            for row in rows_iter:
                if row is None or all(v is None for v in row):
                    continue
                writer.writerow("" if v is None else v for v in row)
                row_count += 1
            if row_count == 0:
                logger.info(
                    "%sxlsx_to_csvs stem=%s: skipping header-only sheet %r (0 data rows)",
                    prefix, stem, ws.title,
                )
                raven_log("DEBUG", "P4", "ingest.xlsx.sheet skipped header only",
                          context={"log_id": log_id, "stem": stem, "sheet": ws.title, "decision": "skip",
                                   "reason_code": "ZERO_DATA_ROWS", "header_columns": len([h for h in header if h])})
                continue

            csv_name = f"{stem}__{_sheet_slug(ws.title)}.csv"
            results.append((buf.getvalue().encode("utf-8"), csv_name))
            raven_log("DEBUG", "P4", "ingest.xlsx.sheet flattened to csv",
                      context={"log_id": log_id, "stem": stem, "sheet": ws.title, "csv_name": csv_name,
                               "rows": row_count, "header_column_names": [h for h in header if h][:100],
                               "decision": "keep"})
        logger.info(
            "xlsx_to_csvs log_id=%s stem=%s sheets_total=%d sheets_ingested=%d",
            log_id, stem, len(wb.worksheets), len(results),
        )
        raven_log("INFO", "P4", "ingest.xlsx.flattened workbook sheets summarised",
                  context={"log_id": log_id, "stem": stem, "sheets_total": len(wb.worksheets),
                           "sheets_ingested": len(results), "zero_sheets": len(results) == 0})
        return results
    finally:
        wb.close()
