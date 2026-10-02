"""Table ownership: the pipeline only ever loads into tables it created.

The names a CSV may be loaded into come from queries in an uploaded XML, i.e. from the
uploader. Without a guard, an XML mentioning ``some_app_table`` plus a CSV named
``some_app_table.csv`` would ``DELETE`` and reload that table. So each table the
pipeline creates is stamped with an owner tag as its table COMMENT, and an existing table
is used only if its comment equals the caller's owner tag (the upload path includes the
workspace id, so two workspaces cannot overwrite each other's tables either). To let the
pipeline manage a table that already exists, an administrator adopts it explicitly::

    COMMENT ON TABLE <table> IS 'csv_bml_ingestion';
"""
from __future__ import annotations

import re

from aryx.csv_bml_ingestion.db import ConnectionFactory
from aryx.csv_bml_ingestion.errors import TableProtectedError

_OWNER_RE = re.compile(r"^[A-Za-z0-9_:=.-]{1,100}$")
_STATE_SQL = (
    "SELECT c.comments FROM user_tables t LEFT JOIN user_tab_comments c "
    "ON c.table_name = t.table_name WHERE t.table_name = %s"
)


def table_state(factory: ConnectionFactory, table: str) -> tuple[bool, str | None]:
    """Return ``(exists, comment)`` for ``table`` in the current schema."""
    with factory() as conn:
        cur = conn.cursor()
        cur.execute(_STATE_SQL, (table.upper(),))
        rows = cur.fetchall()
    return (True, rows[0][0]) if rows else (False, None)


def require_owned_or_absent(factory: ConnectionFactory, table: str, owner: str) -> bool:
    """Return whether ``table`` already exists; raise if it exists but is not owned by ``owner``."""
    exists, comment = table_state(factory, table)
    if exists and comment != owner:
        raise TableProtectedError(
            f"table {table!r} already exists and is not managed by csv_bml_ingestion for this owner "
            f"({owner!r}); refusing to modify it. To let the pipeline manage it, an administrator can run: "
            f"COMMENT ON TABLE {table} IS '{owner}'")
    return exists


def claim_new_table(factory: ConnectionFactory, table: str, owner: str) -> None:
    """Stamp a table this run just created — unless another run claimed it in the meantime.

    Two runs can both see a name as absent and both run ``CREATE TABLE IF NOT EXISTS`` (one is a
    no-op). So the comment is re-read after the DDL: stamp only while it is still empty, and refuse
    if someone else's tag is already there, so a loser of the race never loads into the winner's table.
    """
    _exists, comment = table_state(factory, table)
    if comment == owner:
        return
    if comment is not None:
        raise TableProtectedError(
            f"table {table!r} was claimed by another owner while being created; refusing to modify it")
    mark_owner(factory, table, owner)


def mark_owner(factory: ConnectionFactory, table: str, owner: str) -> None:
    """Stamp a table the pipeline just created with ``owner`` (validated; not user-controlled text)."""
    if not _OWNER_RE.match(owner):
        raise TableProtectedError(f"invalid owner tag {owner!r}")
    with factory() as conn:
        conn.cursor().execute(f"COMMENT ON TABLE {table} IS '{owner}'")
