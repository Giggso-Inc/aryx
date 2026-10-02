"""Relational side of the pipeline: connections, DDL execution, bulk load.

Targets Oracle ADB on ``dev_oci`` through the project's existing pool
(``aryx.store.oracle_pool``), whose cursor already translates ``%s`` binds.
A ``ConnectionFactory`` is injected everywhere so tests use a fake and no
caller hard-codes a backend.
"""
from __future__ import annotations

import logging
from itertools import islice
from typing import Any, Callable, ContextManager, Iterable, Iterator, Sequence

from aryx.csv_bml_ingestion.errors import DatabaseUnavailableError

logger = logging.getLogger(__name__)

ConnectionFactory = Callable[[], ContextManager[Any]]


def oracle_connection_factory() -> ConnectionFactory:
    """Return a factory yielding pooled Oracle ADB connections.

    Raises:
        DatabaseUnavailableError: the app is not configured for the OCI
            (Oracle ADB) relational backend, or the DSN is unset.
    """
    from aryx.config import get_settings  # noqa: PLC0415

    settings = get_settings()
    if settings.effective_db_backend() != "oci":
        raise DatabaseUnavailableError(
            "csv_bml_ingestion targets Oracle ADB: set ARYX_DB_BACKEND=oci (or ARYX_OCI_MODE=true)"
        )
    try:
        dsn = settings.effective_dsn()
    except RuntimeError as exc:
        raise DatabaseUnavailableError(str(exc)) from exc
    from aryx.store.oracle_pool import get_oracle_pool  # noqa: PLC0415

    return lambda: get_oracle_pool(dsn).connection()


def execute_statements(factory: ConnectionFactory, statements: Sequence[str]) -> int:
    """Run each DDL statement in order on one connection; returns how many ran."""
    with factory() as conn:
        for sql in statements:
            logger.debug("csv_bml_ingestion: executing DDL: %.120s", sql)
            conn.cursor().execute(sql)
    return len(statements)


def _batches(rows: Iterable[tuple], size: int) -> Iterator[list[tuple]]:
    it = iter(rows)
    while batch := list(islice(it, size)):
        yield batch


def load_rows(
    factory: ConnectionFactory,
    table: str,
    columns: Sequence[str],
    rows: Iterable[tuple],
    *,
    batch_size: int,
    replace: bool,
    on_batch: Callable[[int], None] | None = None,
) -> int:
    """Insert ``rows`` into ``table`` in one transaction; returns rows inserted.

    ``table`` and ``columns`` must already be validated identifiers (they are
    interpolated). ``replace=True`` first deletes every existing row — a
    transactional DELETE rather than TRUNCATE, so a failed load rolls back to
    the previous contents instead of leaving the table empty. Any exception
    propagates and the pool's context manager rolls the transaction back.
    """
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    insert_sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
    total = 0
    with factory() as conn:
        cur = conn.cursor()
        if replace:
            cur.execute(f"DELETE FROM {table}")
        for batch in _batches(rows, batch_size):
            cur.executemany(insert_sql, batch)
            total += len(batch)
            if on_batch:
                on_batch(total)
    return total
