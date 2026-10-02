"""Policy for values that do not fit their column (ORA-12899 / ORA-01438).

Without a guard, one over-long cell makes Oracle reject an entire
``executemany`` batch and the whole load rolls back. This guard checks every
row against the table's real column limits *before* insert and applies one of
three policies:

* ``reject``   (default) — skip the row, write it with the reason to a
  ``<table>.rejects.csv`` file, count it, and keep loading;
* ``truncate`` — cut text to fit (byte-aware, never splits a UTF-8 character)
  and load the row; numbers cannot be truncated, so those rows are rejected;
* ``fail``     — raise ``ValueTooLongError`` on the first violation (the load
  rolls back, nothing is written).

Text is measured in *bytes* for BYTE-semantics columns: a 1000-byte column
holds fewer than 1000 non-ASCII characters.
"""
from __future__ import annotations

import csv
import logging
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from aryx.csv_bml_ingestion.column_limits import ColumnLimit
from aryx.csv_bml_ingestion.errors import ValueTooLongError
from aryx.csv_bml_ingestion.rejects import RejectCollector, RejectedRow, csv_safe_cell

logger = logging.getLogger(__name__)


class OverflowPolicy(str, Enum):
    """What to do with a value that does not fit."""

    REJECT = "reject"
    TRUNCATE = "truncate"
    FAIL = "fail"


@dataclass(slots=True)
class OverflowReport:
    """Accounting for one load."""

    rows_rejected: int = 0
    rows_truncated: int = 0
    by_column: Counter = field(default_factory=Counter)
    longest: dict[str, int] = field(default_factory=dict)  # column -> longest offending size
    samples: list[str] = field(default_factory=list)
    rejects_file: Path | None = None
    rejects: RejectCollector = field(default_factory=RejectCollector)


def _violation(value: object, col: str, limit: ColumnLimit) -> tuple[str, int] | None:
    """Return (reason, size) if ``value`` does not fit, else None."""
    if value is None:
        return None
    if limit.kind == "text" and isinstance(value, str):
        if limit.max_bytes is not None:
            size = len(value.encode("utf-8"))
            if size > limit.max_bytes:
                return f"{col}: {size} bytes > limit {limit.max_bytes}", size
        elif limit.max_chars is not None and len(value) > limit.max_chars:
            return f"{col}: {len(value)} chars > limit {limit.max_chars}", len(value)
    elif limit.kind == "number" and limit.digits and isinstance(value, int) and not isinstance(value, bool):
        if abs(value) >= 10 ** limit.digits:
            return f"{col}: {value} exceeds {limit.digits} integer digits", len(str(abs(value)))
    return None


def _truncate(value: str, limit: ColumnLimit) -> str:
    if limit.max_bytes is not None:
        return value.encode("utf-8")[: limit.max_bytes].decode("utf-8", "ignore")
    return value[: limit.max_chars]


class _RejectsWriter:
    """Lazily-created rejects CSV: the table's columns plus ``reject_reason``."""

    def __init__(self, path: Path | None, columns: Sequence[str]) -> None:
        self.path, self._columns, self._fh, self._w = path, columns, None, None

    def write(self, row: Sequence[object], reason: str) -> None:
        if self.path is None:
            return
        if self._w is None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._fh = self.path.open("w", encoding="utf-8", newline="")
            except OSError as exc:   # e.g. read-only image: rejects are also stored in the database, keep loading
                logger.warning("csv_bml_ingestion: cannot write rejects file %s: %r", self.path, exc)
                self.path = None
                return
            self._w = csv.writer(self._fh)
            self._w.writerow([*self._columns, "reject_reason"])
        self._w.writerow([*(csv_safe_cell(v) for v in row), reason])

    def close(self) -> None:
        if self._fh:
            self._fh.close()


def guard_rows(
    rows: Iterable[tuple],
    columns: Sequence[str],
    limits: dict[str, ColumnLimit],
    policy: OverflowPolicy,
    report: OverflowReport,
    rejects_path: Path | None,
) -> Iterator[tuple]:
    """Yield only rows that fit (or were truncated to fit), per ``policy``."""
    return guard_numbered_rows(((0, r) for r in rows), columns, limits, policy, report, rejects_path)


def guard_numbered_rows(
    rows: Iterable[tuple[int, tuple]],
    columns: Sequence[str],
    limits: dict[str, ColumnLimit],
    policy: OverflowPolicy,
    report: OverflowReport,
    rejects_path: Path | None,
) -> Iterator[tuple]:
    """``guard_rows`` over ``(source line number, row)`` pairs; rejected rows are also kept
    structurally in ``report.rejects`` (line, reason, column values) so they can be re-run."""
    checked = [(i, c, limits[c]) for i, c in enumerate(columns)
               if c in limits and limits[c].kind in ("text", "number")]
    if rejects_path is not None:
        try:
            rejects_path.unlink(missing_ok=True)  # never leave a previous run's rejects looking current
        except OSError as exc:   # e.g. read-only folder holding an old file
            logger.warning("csv_bml_ingestion: cannot remove old rejects file %s: %r", rejects_path, exc)
    writer = _RejectsWriter(rejects_path, columns)
    try:
        for line_no, row in rows:
            bad = [(c, v) for i, c, lim in checked if (v := _violation(row[i], c, lim))]
            if not bad:
                yield row
                continue
            for col, (reason, size) in bad:
                report.by_column[col] += 1
                report.longest[col] = max(report.longest.get(col, 0), size)
                if len(report.samples) < 5:
                    report.samples.append(reason)
            if policy is OverflowPolicy.FAIL:
                raise ValueTooLongError(f"value does not fit: {bad[0][1][0]} (policy=fail)")
            fixed = _try_truncate(row, columns, limits, bad) if policy is OverflowPolicy.TRUNCATE else None
            if fixed is not None:
                report.rows_truncated += 1
                yield fixed
            else:
                report.rows_rejected += 1
                reason = "; ".join(v[0] for _, v in bad)
                writer.write(row, reason)
                report.rejects_file = writer.path     # None once the file could not be written
                report.rejects.add(RejectedRow(line_no=line_no, code="CBI_VALUE_TOO_LONG", reason=reason[:900],
                                               payload={"columns": dict(zip(columns, row))}))
    finally:
        writer.close()


def _try_truncate(row: tuple, columns: Sequence[str], limits: dict[str, ColumnLimit],
                  bad: list) -> tuple | None:
    """Truncate every offending text cell; None if any offender is a number."""
    out = list(row)
    for col, _ in bad:
        i = columns.index(col)
        if limits[col].kind != "text" or not isinstance(out[i], str):
            return None
        out[i] = _truncate(out[i], limits[col])
    return tuple(out)
