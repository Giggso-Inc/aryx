"""Strict validation of LLM-authored schema/index SQL before it is saved or run.

The LLM chooses the sizes and the indexes; this module only decides whether
what it wrote is acceptable. The whitelist is deliberately narrow — anything
that is not exactly a ``CREATE TABLE IF NOT EXISTS`` with the CSV's columns, or
a ``CREATE INDEX IF NOT EXISTS`` over those columns, is rejected, so a
hallucinated ``DROP``/``GRANT``/second table can never reach the database.

Schema rules: exactly one statement; columns equal the CSV's, in order; text
columns ``VARCHAR2(n)`` with ``observed max bytes <= n <= 4000``; ``Integer``
columns ``NUMBER(p)`` with ``1 <= p <= 38``; no constraints.
Index rules: at most ``MAX_INDEXES``; named ``idx_<table>_*``; only table
columns; no repeats; declared key size ``<= MAX_INDEX_KEY_BYTES`` (ORA-01450).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from aryx.csv_bml_ingestion.errors import SqlAuthoringError
from aryx.csv_bml_ingestion.sql_catalog import split_statements

MAX_VARCHAR = 4000
MAX_INDEXES = 6
MAX_INDEX_KEY_BYTES = 6000      # under the ~6398-byte limit of an 8K block
NUMBER_KEY_BYTES = 22

_COL_RE = re.compile(r"(\w+)\s+(?:VARCHAR2\((\d+)\)|NUMBER\((\d+)\))", re.IGNORECASE | re.ASCII)
_INDEX_RE = re.compile(
    r"CREATE INDEX IF NOT EXISTS (idx_\w{1,100}) ON (\w+) \(\s*(\w+(?:\s*,\s*\w+)*)\s*\)", re.IGNORECASE | re.ASCII)


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """What the CSV requires of one column."""

    name: str
    kind: str           # "text" | "number"
    min_bytes: int = 1  # longest value observed in the CSV: bytes for text, digits for numbers


def validate_schema(sql: str, table: str, specs: list[ColumnSpec]) -> dict[str, int]:
    """Check ``sql``; return ``{column: declared key bytes}`` for the index check."""
    stmts = split_statements(sql)
    if len(stmts) != 1:
        raise SqlAuthoringError(f"schema must be exactly one CREATE TABLE statement, got {len(stmts)}")
    m = re.fullmatch(rf"CREATE TABLE IF NOT EXISTS {re.escape(table)} \((.*)\)", stmts[0], re.IGNORECASE | re.DOTALL | re.ASCII)
    if not m:
        raise SqlAuthoringError(f"schema must be 'CREATE TABLE IF NOT EXISTS {table} (...)' and nothing else")
    cells = [c.strip() for c in m.group(1).split(",")]
    sizes: dict[str, int] = {}
    errors: list[str] = []
    if len(cells) != len(specs):
        raise SqlAuthoringError(f"expected {len(specs)} columns, found {len(cells)}")
    for cell, spec in zip(cells, specs):
        c = _COL_RE.fullmatch(cell)
        if not c or c.group(1).lower() != spec.name:
            errors.append(f"expected column '{spec.name}' (plain VARCHAR2(n)/NUMBER(p)), got '{cell}'")
        elif spec.kind == "text" and c.group(2):
            n = int(c.group(2))
            if not max(1, spec.min_bytes) <= n <= MAX_VARCHAR:
                errors.append(f"{spec.name}: VARCHAR2({n}) must be between {max(1, spec.min_bytes)} (longest CSV value) and {MAX_VARCHAR}")
            sizes[spec.name] = n
        elif spec.kind == "number" and c.group(3):
            if not max(1, spec.min_bytes) <= int(c.group(3)) <= 38:
                errors.append(f"{spec.name}: NUMBER({c.group(3)}) must have precision between {max(1, spec.min_bytes)} (digits in the longest CSV value) and 38")
            sizes[spec.name] = NUMBER_KEY_BYTES
        else:
            errors.append(f"{spec.name}: wrong type for a CSV '{spec.kind}' column")
    if errors:
        raise SqlAuthoringError("; ".join(errors))
    return sizes


def validate_indexes(sql: str, table: str, sizes: dict[str, int]) -> int:
    """Check the index statements; returns how many there are."""
    stmts = split_statements(sql)
    if len(stmts) > MAX_INDEXES:
        raise SqlAuthoringError(f"at most {MAX_INDEXES} indexes allowed, got {len(stmts)}")
    seen_names: set[str] = set()
    seen_cols: set[tuple[str, ...]] = set()
    for stmt in stmts:
        m = _INDEX_RE.fullmatch(stmt)
        if not m or m.group(2).lower() != table:
            raise SqlAuthoringError(f"not an allowed index statement for {table}: {stmt[:120]!r}")
        name, cols = m.group(1).lower(), tuple(c.strip().lower() for c in m.group(3).split(","))
        if not name.startswith(f"idx_{table}_") or name in seen_names or cols in seen_cols or len(set(cols)) != len(cols):
            raise SqlAuthoringError(f"bad or duplicate index {name} on {cols}")
        unknown = [c for c in cols if c not in sizes]
        if unknown:
            raise SqlAuthoringError(f"index {name} uses columns not in the table: {unknown}")
        if sum(sizes[c] for c in cols) > MAX_INDEX_KEY_BYTES:
            raise SqlAuthoringError(f"index {name} key is {sum(sizes[c] for c in cols)} bytes > {MAX_INDEX_KEY_BYTES} (ORA-01450); use smaller columns or fewer index columns")
        seen_names.add(name)
        seen_cols.add(cols)
    return len(stmts)
