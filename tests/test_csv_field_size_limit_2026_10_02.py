"""RCA (docs/CPQ_APX900_BmFunction_SourceFile_Investigation_2026-09-21.md):
a bm_function row's script_text field exceeded Python csv's default 128 KiB
(131072 byte) per-field limit, raising csv.Error and silently dropping the
ENTIRE BmFunction entity type from ingestion for a real workspace -- caught
per-plan in ingest_confirmed's parallel loop, logged as one WARNING, job
continued with the other 31 files, overall status still "success".

Fix: csv.field_size_limit() raised at import time in both real call sites
(src/aryx/connectors/csv_source.py's CsvConnector -- actual ingestion --
and src/aryx/pipeline/ingest_validation.py's _parse_csv -- post-ingest
validation, which crashed on the exact same field independently).

These tests reproduce the exact failure signature with a synthetic field
over the 131072-byte default limit (never the real sample file) and confirm
both call sites now parse it successfully instead of raising.
"""
from __future__ import annotations

import csv as csv_module
import sys

from aryx.connectors.csv_source import CsvConnector
from aryx.pipeline.ingest_validation.ingest_validation_ground_truth import (
    _parse_csv,
    ground_truth_from_tabular,
)

_OVERSIZED_FIELD_LEN = 131072 + 1024  # just past the default limit


def _make_oversized_csv() -> bytes:
    big_script = "x" * _OVERSIZED_FIELD_LEN
    header = "_element_type,id,script_text\n"
    row = f'bm_function,F1,"{big_script}"\n'
    return (header + row).encode("utf-8")


def test_field_size_limit_is_raised_above_the_python_default() -> None:
    # The default (128 KiB) is exactly what caused the live failure; confirm
    # the process-wide limit is now well past it after importing either
    # fixed module (import already happened above, at module load time).
    assert csv_module.field_size_limit() > 131072


def test_field_size_limit_is_a_bounded_cap_not_the_platform_maximum() -> None:
    """PR #345 review, M1: raising to sys.maxsize would remove csv's own
    guard against a malformed/unterminated-quote file being parsed as one
    unbounded field. The fix must raise a generous but still-bounded cap
    (50 MiB) instead, so that guard still fires for a genuinely malformed
    upload rather than silently ballooning memory."""
    limit = csv_module.field_size_limit()
    assert limit == 50 * 1024 * 1024
    assert limit < sys.maxsize


def test_csv_connector_parses_a_field_past_the_default_limit() -> None:
    """This is the real ingestion path (CsvConnector, used inside
    run_pipeline) -- confirmed live to be the one that actually dropped
    BmFunction. Before the fix, this raised
    csv.Error: field larger than field limit (131072)."""
    data = _make_oversized_csv()
    records = list(CsvConnector(data, system="csv", dataset="bm_function").extract())
    assert len(records) == 1
    assert len(records[0].payload["script_text"]) == _OVERSIZED_FIELD_LEN


def test_parse_csv_handles_a_field_past_the_default_limit() -> None:
    """The post-ingest validation path (ingest_validation._parse_csv) hit
    the identical crash independently, as its own separate "validation
    crashed" warning in the live log."""
    data = _make_oversized_csv()
    headers, rows = _parse_csv(data)
    assert "script_text" in headers
    assert len(rows) == 1
    assert len(rows[0]["script_text"]) == _OVERSIZED_FIELD_LEN


def test_ground_truth_from_tabular_no_longer_crashes_on_an_oversized_field() -> None:
    """End-to-end: the exact call that produced the live "validation
    crashed: field larger than field limit (131072)" traceback
    (doc_discovery.py's ingest_confirmed -> ground_truth_from_tabular ->
    _parse_csv) must now succeed instead of raising."""
    plans = [{"filename": "aSTRO25_ConfigData_bm_function.csv", "data": _make_oversized_csv()}]
    gt = ground_truth_from_tabular(plans)
    assert gt.datasets["aSTRO25_ConfigData_bm_function"].rows == 1
