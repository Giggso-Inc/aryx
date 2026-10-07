"""A workspace's CSV tables as Data Table rows for the CPQ engine (Oracle ADB).

The CSV pipeline (``aryx.csv_bml_ingestion``) loads each CSV into its own table,
``ws<workspace id>_<file stem>``, because that is what the XML scripts query (``select ... from newCountryRegMapping``).
The engine's Data Table loaders were built for the older path that stored CSV rows as ``aryx_entity`` rows, so they
never looked at these tables. This module lets the Oracle CPQ reader (``rdb_oracle``) answer the same questions from
the tables, with rows shaped like the entity rows the engine already understands:

* only the tables the pipeline owns for THIS workspace are read (owner tag in the table comment AND the exact
  ``ws<id>_`` name, so workspace 7 never reads ``ws70_...``);
* a table is skipped when entity rows already exist for the same logical name (nothing is double counted);
* column names come back lower-case from Oracle, the CSV headers were camelCase (``ruleType``, ``UDCC``): known
  spellings are restored (``CANONICAL_COLUMNS``) and the row also answers ``get``/``[]`` case-insensitively;
* NULL cells are left out of the row, like an empty CSV cell was never stored on an entity;
* a table is read only when its columns satisfy the caller's shape test, so the big tables no consumer asks for
  (a 450k-row formula table, a 180k-row customer table) are never loaded.

Everything is best effort and read-only: a failure returns nothing and the engine behaves as before.
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Iterable
from typing import Any

logger = logging.getLogger(__name__)

MAX_ROWS_ENV = "ARYX_CPQ_WS_TABLE_MAX_ROWS"
DEFAULT_MAX_ROWS = 500_000
_LISTING_TTL_SECONDS = 30.0
_FETCH_BATCH = 5000

# The spellings the engine's shape detectors (cpq/data_table/data_table_shapes.py) and the Data Table readers use.
# tests/test_cpq_rdb_workspace_tables.py checks every detector spelling is listed here.
CANONICAL_COLUMNS: tuple[str, ...] = (
    "CPQModel", "BaseModel", "AttrName", "Seq", "optionOrReqFlag", "Product", "cpqModelName", "childCPQModel",
    "cpqModel", "group", "attributeName", "attributeVariable", "model", "value", "region", "ruleType", "attribute",
    "UDCC", "countryCode", "RTTE", "nonRTTE", "TA", "startDate", "endDate", "partNumber",
    "baseModel", "displayModel",     # BaseModelToConfig shape (data_table_inference._is_basemodel_to_config_shaped)
)
# two shapes spell one column differently ("CPQModel" vs "cpqModel"), so a lower-case name can have several spellings
_CANONICAL: dict[str, tuple[str, ...]] = {}
for _name in CANONICAL_COLUMNS:
    _CANONICAL[_name.lower()] = (*_CANONICAL.get(_name.lower(), ()), _name)

_LISTING_CACHE: dict[int, tuple[float, dict[str, str]]] = {}


class TableRow(dict):
    """A table row that also answers ``get`` / ``[]`` / ``in`` case-insensitively (``row.get("ruleType")`` for ``ruletype``)."""

    __slots__ = ("_by_lower",)

    def __init__(self, items: Iterable[tuple[str, Any]] = (), by_lower: dict[str, str] | None = None) -> None:
        super().__init__(items)
        # a table passes ONE shared index for all its rows (a row only misses the columns it has no value for)
        self._by_lower = by_lower if by_lower is not None else {str(k).lower(): k for k in self}

    def _resolve(self, key: Any) -> Any:
        return key if dict.__contains__(self, key) else self._by_lower.get(str(key).lower(), key)

    def __getitem__(self, key: Any) -> Any:
        return super().__getitem__(self._resolve(key))

    def get(self, key: Any, default: Any = None) -> Any:
        return super().get(self._resolve(key), default)

    def __contains__(self, key: Any) -> bool:
        return super().__contains__(self._resolve(key))


def normalized(name: str) -> str:
    """Lower-case, underscores removed: how the reader compares ontology type names with table names."""
    return (name or "").lower().replace("_", "")


def recase(column: str, variant: int = 0) -> str:
    """The engine's spelling of a column (``ruletype`` -> ``ruleType``); unknown columns stay lower-case.

    ``variant`` picks among the spellings of an ambiguous name (``CPQModel`` is 0, ``cpqModel`` is 1).
    """
    lowered = column.lower()
    spellings = _CANONICAL.get(lowered)
    return spellings[min(variant, len(spellings) - 1)] if spellings else lowered


_SPELLING_VARIANTS = (0, 1)


def max_rows() -> int:
    """Per-table row cap (``ARYX_CPQ_WS_TABLE_MAX_ROWS``); a bad value falls back to the default."""
    try:
        return max(1, int(os.environ.get(MAX_ROWS_ENV, DEFAULT_MAX_ROWS)))
    except ValueError:
        return DEFAULT_MAX_ROWS


def workspace_tables(conn: Any, workspace_id: int) -> dict[str, str]:
    """{logical table name -> physical table name} the CSV pipeline owns for ``workspace_id`` (cached ~30 s)."""
    from aryx.csv_bml_ingestion.ownership import workspace_owner  # noqa: PLC0415
    from aryx.csv_bml_ingestion.table_naming import WORKSPACE_PREFIX, is_workspace_table  # noqa: PLC0415

    now = time.monotonic()
    hit = _LISTING_CACHE.get(workspace_id)
    if hit is not None and now - hit[0] < _LISTING_TTL_SECONDS:
        return hit[1]
    found: dict[str, str] = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT t.table_name FROM user_tables t JOIN user_tab_comments c ON c.table_name = t.table_name "
            "WHERE c.comments = :1",
            (workspace_owner(workspace_id),),
        )
        for (name,) in cur.fetchall():
            physical = str(name).lower()
            if is_workspace_table(physical, workspace_id):
                found[physical[len(f"{WORKSPACE_PREFIX}{int(workspace_id)}_"):]] = physical
    _LISTING_CACHE[workspace_id] = (now, found)
    return found


def groups_from(
    rdb: Any, workspace_id: int, accept: Callable[[set[str]], bool], skip_types: Iterable[str] = (),
) -> dict[str, list[tuple[int, dict[str, Any]]]]:
    """``rdb.fetch_workspace_table_groups(...)`` for the Data Table scans; {} when the reader has none (or it fails)."""
    fetch = getattr(rdb, "fetch_workspace_table_groups", None)
    if fetch is None:
        return {}
    try:
        groups = fetch(workspace_id, accept, skip_types)
    except Exception:  # noqa: BLE001  a table read must never break a Data Table scan
        logger.warning("cpq: workspace tables unavailable ws=%s", workspace_id, exc_info=True)
        return {}
    return groups if isinstance(groups, dict) else {}


def clear_listing_cache() -> None:
    """Forget the cached table listing (tests, and a new load that must show up at once)."""
    _LISTING_CACHE.clear()


def _columns(conn: Any, physical: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT column_name FROM user_tab_columns WHERE table_name = :1 ORDER BY column_id", (physical.upper(),))
        return [str(r[0]) for r in cur.fetchall()]


def _read(
    conn: Any, physical: str, columns: list[str], variant: int = 0, first_id: int = -1,
) -> list[tuple[int, dict[str, Any]]]:
    """Every row of ``physical`` (up to the cap) as (synthetic negative id, row); NULL cells are left out.

    Ids count down from ``first_id`` (-1, -2, ...), so a caller reading several tables can keep them unique.
    """
    names = [recase(c, variant) for c in columns]
    by_lower = {n.lower(): n for n in names}
    select = ", ".join(f'"{c}"' for c in columns)        # quoted: KEY / VALUE are column names here
    cap = max_rows()
    rows: list[tuple[int, dict[str, Any]]] = []
    with conn.cursor() as cur:
        cur.arraysize = _FETCH_BATCH
        cur.execute(f"SELECT {select} FROM {physical}")  # noqa: S608  physical is checked by is_workspace_table
        while len(rows) < cap:
            batch = cur.fetchmany(_FETCH_BATCH)
            if not batch:
                break
            for values in batch:
                if len(rows) >= cap:
                    break
                row = TableRow(((n, v) for n, v in zip(names, values) if v is not None), by_lower)
                rows.append((first_id - len(rows), row))   # negative ids never collide with aryx_entity ids
    if len(rows) >= cap:
        logger.warning("cpq: workspace table %s read capped at %d rows (%s)", physical, cap, MAX_ROWS_ENV)
    return rows


def rows_for_type(conn: Any, workspace_id: int, ontology_type: str, *, suffix: bool = False) -> list[tuple[int, dict[str, Any]]]:
    """Rows of the workspace table whose logical name equals ``ontology_type`` (or ends with it, when ``suffix``)."""
    wanted = normalized(ontology_type)
    tables = workspace_tables(conn, workspace_id)
    exact = [p for logical, p in tables.items() if normalized(logical) == wanted]
    if exact:
        return _read(conn, exact[0], _columns(conn, exact[0]))
    ending = [p for logical, p in tables.items() if suffix and wanted and normalized(logical).endswith(wanted)]
    if len(ending) == 1:                               # exactly one table ends with it; two would be a guess
        return _read(conn, ending[0], _columns(conn, ending[0]))
    return []


def grouped_rows(
    conn: Any, workspace_id: int, accept: Callable[[set[str]], bool], skip_types: Iterable[str] = (),
) -> dict[str, list[tuple[int, dict[str, Any]]]]:
    """{logical name -> rows} for each workspace table whose (re-cased) columns satisfy ``accept``.

    ``skip_types`` are entity types that already exist: a table with the same logical name is not read again.
    """
    skip = {normalized(t) for t in skip_types}
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    next_id = -1
    for logical, physical in workspace_tables(conn, workspace_id).items():
        if normalized(logical) in skip:
            continue
        columns = _columns(conn, physical)
        variant = next((v for v in _SPELLING_VARIANTS if columns and accept({recase(c, v) for c in columns})), None)
        if variant is None:
            continue
        grouped[logical] = _read(conn, physical, columns, variant, next_id)
        next_id -= len(grouped[logical])               # the next table continues below this one: ids stay unique
    return grouped
