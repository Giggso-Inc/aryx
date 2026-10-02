"""Step 1 — derive the target table name from a CSV filename."""
from __future__ import annotations

import re
from pathlib import Path

from aryx.csv_bml_ingestion.constants import TABLE_NAME_RE
from aryx.csv_bml_ingestion.errors import InvalidTableNameError, TableNameMissingError

_SUPPORTED_SUFFIXES = {".csv", ".xlsx", ".xls"}


def extract_table_name(filename: str | Path | None) -> str:
    """Return the lowercase table name for ``filename`` (its stem).

    The name is lowercased here, once, and that lowercase form is used for
    both the XML/BML comparison and the SQL objects, so mixed-case file names
    (``attrToPart.csv``) and mixed-case queries (``FROM attrToPart``) always
    compare equal.

    Raises:
        TableNameMissingError: ``filename`` is None, empty, or has no stem.
        InvalidTableNameError: the stem is not a safe SQL identifier
            (``[a-z][a-z0-9_]*`` after lowercasing).
    """
    if filename is None or not str(filename).strip():
        raise TableNameMissingError("no filename supplied; cannot derive a table name")
    path = Path(str(filename).strip())
    if path.name.lower() in _SUPPORTED_SUFFIXES:  # a bare ".csv": extension but no stem
        raise TableNameMissingError(f"filename {str(filename)!r} has no stem, only an extension")
    stem = path.stem if path.suffix.lower() in _SUPPORTED_SUFFIXES else path.name
    name = stem.strip().lower()
    if not name:
        raise TableNameMissingError(f"filename {str(filename)!r} has no usable stem")
    if not re.match(TABLE_NAME_RE, name):
        raise InvalidTableNameError(
            f"table name {name!r} (from {str(filename)!r}) is not a safe SQL identifier "
            f"(expected {TABLE_NAME_RE})"
        )
    return name
