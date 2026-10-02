"""Per-workspace data tables go with the workspace.

Each workspace's CSV data lives in its own tables (``ws<id>_<file stem>``, see ``table_naming``). When a
workspace is purged, deleted, or the whole system is reset, those tables are dropped.

A table is dropped only if BOTH hold, so nothing else can ever be touched:

* its table COMMENT is the pipeline's owner tag for that workspace (``csv_bml_ingestion:ws=<id>``), and
* its name is exactly ``ws<id>_…`` for that same id (so workspace 7 never matches ``ws70_…``).

Tables created before per-workspace naming (plain ``attrsequence``) carry no such name and are left alone.
Callers run this best-effort and in its own transaction (see ``OracleWorkspaceStore._purge_csv_issues``): a
failure here must never fail a workspace delete.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path

from aryx.csv_bml_ingestion.constants import OWNER_TAG, default_sql_root
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


_WS_DIR_RE = re.compile(r"^ws_\d+$")


def remove_workspace_files(workspace_id: int | None, *, whole_workspace: bool) -> list[str]:
    """Remove the per-workspace files this pipeline wrote on disk; returns what was removed.

    Rejected rows are written as plaintext CSV under ``<sql dir>/ws_<id>/_rejects``; they are customer data
    and must not outlive the workspace's data. ``whole_workspace`` (workspace delete / factory reset) also
    removes the authored SQL under ``ws_<id>/``; a plain data purge keeps it so it is not re-authored.
    ``workspace_id=None`` means every workspace. Only directories named exactly ``ws_<digits>`` are touched.
    """
    removed = _remove_override_rejects(workspace_id)
    root = default_sql_root()
    if not root.is_dir():
        return removed
    if workspace_id is None:
        dirs = [d for d in root.iterdir() if d.is_dir() and _WS_DIR_RE.match(d.name)]
    else:
        dirs = [root / f"ws_{int(workspace_id)}"]
    for d in dirs:
        target = d if whole_workspace else d / "_rejects"
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target, ignore_errors=True)
            removed.append(str(target))
    return removed


_REJECTS_FILE_RE = re.compile(r"^ws(\d+)_[a-z][a-z0-9_]*\.rejects\.csv$")


def _remove_override_rejects(workspace_id: int | None) -> list[str]:
    """Rejects written to the ``ARYX_CSV_BML_REJECTS_DIR`` override are flat ``ws<id>_<table>.rejects.csv`` files.

    Only files with exactly that name for the workspace are removed (``ws7`` never matches ``ws70``).
    """
    folder = os.environ.get("ARYX_CSV_BML_REJECTS_DIR", "").strip()
    if not folder or not Path(folder).is_dir():
        return []
    removed: list[str] = []
    for f in Path(folder).iterdir():
        m = _REJECTS_FILE_RE.match(f.name)
        if not m or not f.is_file() or f.is_symlink():
            continue
        if workspace_id is not None and int(m.group(1)) != int(workspace_id):
            continue
        try:
            f.unlink()
            removed.append(str(f))
        except OSError:
            logger.warning("csv_bml_ingestion: could not remove %s", f, exc_info=True)
    return removed
