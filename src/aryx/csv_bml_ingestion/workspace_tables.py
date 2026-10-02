"""Per-workspace data tables go with the workspace.

Each workspace's CSV data lives in its own tables (``ws<id>_<file stem>``, see ``table_naming``). When a
workspace is purged, deleted, or the whole system is reset, those tables are dropped.

A table is dropped only if BOTH hold, so nothing else can ever be touched:

* its table COMMENT is the pipeline's owner tag for that workspace (``csv_bml_ingestion:ws=<id>``), and
* its name is exactly ``ws<id>_…`` for that same id (so workspace 7 never matches ``ws70_…``).

Tables created before per-workspace naming (plain ``attrsequence``) carry no such name and are left alone.
Callers run this best-effort and in its own transaction (see ``OracleWorkspaceStore._purge_csv_data``): a
failure here must never fail a workspace delete.
"""
from __future__ import annotations

import logging
import re

from aryx.csv_bml_ingestion.constants import OWNER_TAG
from aryx.csv_bml_ingestion.db import ConnectionFactory
from aryx.csv_bml_ingestion.ownership import workspace_owner
from aryx.csv_bml_ingestion.table_naming import is_workspace_table

logger = logging.getLogger(__name__)

_OWNED = (
    "SELECT t.table_name, c.comments FROM user_tables t JOIN user_tab_comments c "
    "ON c.table_name = t.table_name WHERE INSTR(c.comments, %s) = 1"
)
_TAG_RE = re.compile(rf"^{re.escape(OWNER_TAG)}:ws=(\d+)$")


def drop_workspace_tables(factory: ConnectionFactory, workspace_id: int | None) -> list[str]:
    """Drop the per-workspace tables of ``workspace_id`` (``None`` = every workspace); returns their names."""
    prefix = f"{OWNER_TAG}:ws=" if workspace_id is None else workspace_owner(workspace_id)
    dropped: list[str] = []
    with factory() as conn:
        cur = conn.cursor()
        cur.execute(_OWNED, (prefix,))
        for name, comment in cur.fetchall():
            match = _TAG_RE.match(str(comment or ""))
            table = str(name).lower()
            if not match or not is_workspace_table(table, int(match.group(1))):
                continue                                   # legacy / differently named: never dropped
            if workspace_id is not None and int(match.group(1)) != int(workspace_id):
                continue
            try:
                cur.execute(f"DROP TABLE {table} PURGE")
            except Exception:  # noqa: BLE001  e.g. ORA-00054 while a load holds it: keep going with the rest
                logger.warning("csv_bml_ingestion: could not drop %s", table, exc_info=True)
                continue
            dropped.append(table)
    if dropped:
        logger.info("csv_bml_ingestion: dropped workspace tables %s", dropped)
    return dropped
