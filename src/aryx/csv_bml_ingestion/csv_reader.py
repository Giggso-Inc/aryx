"""Reader for the ``_start meta data`` / ``_end meta data`` CSV layout.

Layout::

    _start meta data
    <header row>
    <type row>          (String / Integer)
    <description row>
    _end meta data
    <data rows...>

Cells that are empty become ``None``. ``Integer`` columns are converted to
``int``; a value that does not parse is reported as a bad row (the row is
skipped and counted, not fatal). Rows whose width differs from the header are
also bad rows.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from aryx.csv_bml_ingestion.constants import CSV_META_END, CSV_META_START, ORACLE_RESERVED
from aryx.csv_bml_ingestion.errors import CsvFormatError
from aryx.csv_bml_ingestion.rejects import BAD_ROW, RejectCollector, RejectedRow

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def to_column_name(header: str) -> str:
    """Map a CSV header cell to its SQL column name (shared with the .sql files).

    Lowercase; runs of non-alphanumerics become ``_``; leading/trailing ``_``
    stripped; an Oracle reserved word gets a ``_col`` suffix.
    """
    name = _NON_ALNUM.sub("_", header.strip().lower()).strip("_")
    if not name:
        raise CsvFormatError(f"header cell {header!r} has no usable column name")
    if name[0].isdigit():
        name = f"c_{name}"
    return f"{name}_col" if name in ORACLE_RESERVED else name


@dataclass(slots=True)
class CsvStats:
    """Row accounting for one read."""

    rows_read: int = 0
    rows_bad: int = 0
    bad_samples: list[str] = field(default_factory=list)
    rejects: RejectCollector = field(default_factory=RejectCollector)


@dataclass(frozen=True, slots=True)
class CsvLayout:
    """Parsed meta block: SQL column names plus per-column Python converters."""

    columns: tuple[str, ...]
    types: tuple[str, ...]
    data_start_line: int


def _convert_cell(type_name: str) -> Callable[[str], object]:
    if type_name.strip().lower() == "integer":
        return lambda s: int(s.strip()) if s.strip() else None
    return lambda s: s if s != "" else None


def read_layout(path: Path, encoding: str = "utf-8-sig") -> CsvLayout:
    """Parse only the meta block of ``path``."""
    try:
        with path.open(encoding=encoding, newline="") as fh:
            rows = csv.reader(fh)
            first = next(rows, None)
            if not first or first[0].strip().lower() != CSV_META_START:
                raise CsvFormatError(f"{path.name}: first line must be {CSV_META_START!r}")
            header = next(rows, None)
            types = next(rows, None)
            if not header or not types or len(header) != len(types):
                raise CsvFormatError(f"{path.name}: header/type rows missing or different widths")
            line = 3
            for row in rows:
                line += 1
                if row and row[0].strip().lower() == CSV_META_END:
                    cols = tuple(to_column_name(h) for h in header)
                    if len(set(cols)) != len(cols):
                        raise CsvFormatError(f"{path.name}: duplicate column names after normalising {cols}")
                    return CsvLayout(columns=cols, types=tuple(types), data_start_line=line + 1)
            raise CsvFormatError(f"{path.name}: no {CSV_META_END!r} line found")
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise CsvFormatError(f"{path}: cannot read CSV: {exc}") from exc


def iter_rows(path: Path, layout: CsvLayout, stats: CsvStats,
              encoding: str = "utf-8-sig") -> Iterator[tuple[object, ...]]:
    """Yield converted data rows; bad rows are counted in ``stats`` and skipped."""
    for _line_no, row in iter_numbered_rows(path, layout, stats, encoding):
        yield row


def iter_numbered_rows(path: Path, layout: CsvLayout, stats: CsvStats,
                       encoding: str = "utf-8-sig") -> Iterator[tuple[int, tuple[object, ...]]]:
    """Like ``iter_rows`` but yields ``(source line number, row)``; bad rows are kept in ``stats.rejects``."""
    converters = [_convert_cell(t) for t in layout.types]
    width = len(layout.columns)
    try:
        with path.open(encoding=encoding, newline="") as fh:
            for line_no, row in enumerate(csv.reader(fh), start=1):
                if line_no < layout.data_start_line or not row:
                    continue
                stats.rows_read += 1
                if len(row) != width:
                    _bad(stats, line_no, f"expected {width} cells, got {len(row)}", row)
                    continue
                try:
                    converted = tuple(conv(cell) for conv, cell in zip(converters, row))
                except ValueError as exc:
                    _bad(stats, line_no, str(exc), row)
                    continue
                yield line_no, converted
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise CsvFormatError(f"{path}: cannot read CSV: {exc}") from exc


def _bad(stats: CsvStats, line_no: int, why: str, cells: list[str]) -> None:
    stats.rows_bad += 1
    stats.rejects.add(RejectedRow(line_no=line_no, code=BAD_ROW, reason=why[:900], payload={"cells": list(cells)}))
    if len(stats.bad_samples) < 5:
        stats.bad_samples.append(f"line {line_no}: {why}")


def profile_max_bytes(path: Path, layout: CsvLayout, encoding: str = "utf-8-sig") -> dict[str, int]:
    """Longest value per column, in UTF-8 bytes (min 1) — sizes the LLM-authored columns."""
    longest = [1] * len(layout.columns)
    for row in iter_rows(path, layout, CsvStats(), encoding):
        for i, v in enumerate(row):
            if v is not None:
                longest[i] = max(longest[i], len(str(v).encode("utf-8")))
    return dict(zip(layout.columns, longest))
