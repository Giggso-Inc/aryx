"""Structured records of CSV rows that were not loaded, kept so they can be shown and re-run.

A row can be left out for two reasons, both captured here with its source line number:

* ``CBI_BAD_ROW``        malformed (wrong cell count, non-integer in an Integer column) —
  payload ``{"cells": [...]}``, the raw cells as read;
* ``CBI_VALUE_TOO_LONG`` parsed fine but a value does not fit its column — payload
  ``{"columns": {name: value}}``, which is what a re-run inserts after the column is widened.

The list is capped (``ARYX_CSV_BML_MAX_REJECT_ROWS``, default 10,000) so one terrible file
cannot flood the database; the true total is still counted and reported.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

BAD_ROW = "CBI_BAD_ROW"
MAX_ROWS_ENV = "ARYX_CSV_BML_MAX_REJECT_ROWS"
DEFAULT_MAX_ROWS = 10_000


def csv_safe_cell(v: object) -> object:
    """Blank for None; prefix ``'`` on text a spreadsheet would run as a formula (``= + - @``, tab, CR)."""
    if v is None:
        return ""
    return "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def max_reject_rows() -> int:
    """Cap on stored reject rows per run (env override, read at call time)."""
    try:
        return max(0, int(os.environ.get(MAX_ROWS_ENV, DEFAULT_MAX_ROWS)))
    except ValueError:
        return DEFAULT_MAX_ROWS


@dataclass(frozen=True, slots=True)
class RejectedRow:
    """One row that was not loaded."""

    line_no: int
    code: str
    reason: str
    payload: dict


@dataclass(slots=True)
class RejectCollector:
    """Keeps the first ``max_rows`` rejected rows and counts all of them."""

    max_rows: int = field(default_factory=max_reject_rows)
    rows: list[RejectedRow] = field(default_factory=list)
    total: int = 0

    def add(self, row: RejectedRow) -> None:
        """Count ``row`` and keep it while under the cap."""
        self.total += 1
        if len(self.rows) < self.max_rows:
            self.rows.append(row)

    @property
    def capped(self) -> bool:
        """True when more rows were rejected than are kept."""
        return self.total > len(self.rows)
