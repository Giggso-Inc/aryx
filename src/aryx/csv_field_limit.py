"""Process-wide csv field size limit shared by the CSV parse call sites.

Python's csv module defaults to a 128 KiB per-field limit; a real
bm_function ``script_text`` field exceeded it and silently dropped a whole
entity type from ingestion (#345). A bounded 50 MiB cap keeps csv's
fast-fail guard against a malformed/unterminated-quote upload.
"""
from __future__ import annotations

import csv

CSV_FIELD_SIZE_LIMIT = 50 * 1024 * 1024  # 50 MiB


def raise_csv_field_size_limit() -> None:
    """Raise csv.field_size_limit to CSV_FIELD_SIZE_LIMIT, halving on
    OverflowError until the platform accepts a value."""
    limit = CSV_FIELD_SIZE_LIMIT
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 2


raise_csv_field_size_limit()
