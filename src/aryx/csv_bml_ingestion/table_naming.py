"""Per-workspace table names: the same CSV in two workspaces must never share a table.

Two names are in play:

* the **logical** name — the lowercase CSV filename stem (``attrsequence``). Steps 1 and 2 use only
  this: it is what the BML queries say, and it names the SQL folder ``<sql dir>/<logical>/``;
* the **physical** name — the Oracle table, ``ws<workspace id>_<logical>`` (``ws7_attrsequence``).
  Ownership, DDL, the load, stored issues and re-runs all use this.

``physical_table`` is the one place the physical name is built. The saved/authored SQL keeps the logical
name (so the same files serve every workspace and the validator is unchanged); ``rename_statements``
swaps the physical name in when the already-validated statements are applied. The swap is anchored to the
only two statement shapes the validator allows, so it cannot touch anything else.
"""
from __future__ import annotations

import re

from aryx.csv_bml_ingestion.constants import TABLE_NAME_RE
from aryx.csv_bml_ingestion.errors import InvalidTableNameError, SqlUnsafeError

WORKSPACE_PREFIX = "ws"


def physical_table(logical: str, workspace_id: int) -> str:
    """Oracle table name for ``logical`` in ``workspace_id``: ``ws<id>_<logical>``.

    Raises:
        InvalidTableNameError: the combined name no longer fits the identifier rule (too long).
    """
    name = f"{WORKSPACE_PREFIX}{int(workspace_id)}_{logical}"
    if not re.match(TABLE_NAME_RE, name):
        raise InvalidTableNameError(
            f"table name {name!r} is too long once the workspace prefix is added "
            f"(file name stem {logical!r}); shorten the file name")
    return name


def is_workspace_table(name: str, workspace_id: int) -> bool:
    """True for a name built by ``physical_table`` for this workspace (used to bound clean-up)."""
    return re.fullmatch(rf"{WORKSPACE_PREFIX}{int(workspace_id)}_[a-z][a-z0-9_]*", name.lower()) is not None


def rename_statements(statements: tuple[str, ...], logical: str, physical: str) -> tuple[str, ...]:
    """Apply ``physical`` in place of ``logical`` in validated CREATE TABLE / CREATE INDEX statements.

    Raises:
        SqlUnsafeError: a statement is not one of the two validated shapes (cannot happen after
            ``validate_statements``; this is the safety net, not an expected path).
    """
    if logical == physical:
        return statements
    lg, ph = re.escape(logical), physical
    table_re = re.compile(rf"^(CREATE TABLE IF NOT EXISTS ){lg}(\s*\()", re.IGNORECASE | re.ASCII)
    index_re = re.compile(rf"^(CREATE INDEX IF NOT EXISTS )idx_{lg}_(\w+)( ON ){lg}(\s*\()", re.IGNORECASE | re.ASCII)
    out: list[str] = []
    for stmt in statements:
        if table_re.match(stmt):
            out.append(table_re.sub(rf"\g<1>{ph}\g<2>", stmt, count=1))
        elif index_re.match(stmt):
            out.append(index_re.sub(rf"\g<1>idx_{ph}_\g<2>\g<3>{ph}\g<4>", stmt, count=1))
        else:
            raise SqlUnsafeError(f"cannot apply a workspace table name to statement: {stmt[:80]!r}")
    return tuple(out)
