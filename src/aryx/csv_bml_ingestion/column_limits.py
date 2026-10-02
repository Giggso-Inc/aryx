"""Read the real column limits of a table from the database.

The database, not the ``.sql`` file, is the source of truth for what fits: a
table may predate the file, be tuned by a DBA, or use CHAR semantics. Limits
are fetched once per ingestion, after the schema has been applied.
"""
from __future__ import annotations

from dataclasses import dataclass

from aryx.csv_bml_ingestion.db import ConnectionFactory

_TEXT_TYPES = {"VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR"}

_LIMITS_SQL = (
    "SELECT column_name, data_type, data_length, char_length, char_used, data_precision, data_scale "
    "FROM user_tab_columns WHERE table_name = %s"
)


@dataclass(frozen=True, slots=True)
class ColumnLimit:
    """What a single column can hold. ``kind`` is ``text``, ``number`` or ``other``."""

    kind: str
    max_bytes: int | None = None   # text, BYTE semantics
    max_chars: int | None = None   # text, CHAR semantics
    digits: int | None = None      # number: integer digits allowed, precision - scale


def fetch_column_limits(factory: ConnectionFactory, table: str) -> dict[str, ColumnLimit]:
    """Return ``{lowercase column name: ColumnLimit}`` for ``table`` (empty if it does not exist)."""
    with factory() as conn:
        cur = conn.cursor()
        cur.execute(_LIMITS_SQL, (table.upper(),))
        rows = cur.fetchall()
    return {str(name).lower(): _limit(dtype, dlen, clen, cused, prec, scale)
            for name, dtype, dlen, clen, cused, prec, scale in rows}


def _limit(dtype: str, data_length: int | None, char_length: int | None,
           char_used: str | None, precision: int | None,
           scale: int | None) -> ColumnLimit:
    if dtype in _TEXT_TYPES:
        if char_used == "C":
            return ColumnLimit("text", max_chars=int(char_length or 0) or None)
        return ColumnLimit("text", max_bytes=int(data_length or 0) or None)
    if dtype == "NUMBER":
        return ColumnLimit("number", digits=int(precision) - int(scale or 0) if precision else None)
    return ColumnLimit("other")
