"""Re-run rejected rows of a stored run.

Typical use: rows were rejected because a value did not fit its column; an admin widens the column
(``ALTER TABLE ... MODIFY``) and re-runs. Each stored over-length row keeps its parsed column values
(``{"columns": {...}}``) so it can be inserted again exactly as it would have been.

Guarantees:

* **One transaction.** Claim the open rows, insert the ones that now fit, update their states, commit.
  An error rolls everything back (rows stay ``open``, nothing is inserted).
* **No double inserts.** Claiming moves rows to ``retrying`` under row locks; a concurrent re-run of
  the same run blocks, then finds nothing left to claim.
* **Only tables the pipeline owns** (see ``ownership``) and columns that really exist in the table.
* Malformed rows (``{"cells": [...]}``: wrong width / bad integer) cannot be inserted as stored; they
  stay ``open`` and are reported as ``not_rerunnable``.
"""
from __future__ import annotations

import re
from typing import Any

from aryx.csv_bml_ingestion.column_limits import fetch_column_limits
from aryx.csv_bml_ingestion.db import ConnectionFactory
from aryx.csv_bml_ingestion.errors import CsvBmlIngestionError
from aryx.csv_bml_ingestion.issue_store import STATE_OPEN, IssueStore
from aryx.csv_bml_ingestion.overflow import OverflowPolicy, OverflowReport, guard_numbered_rows
from aryx.csv_bml_ingestion.ownership import require_owned_or_absent, workspace_owner

_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_ID_COL = "__reject_id"


class RerunError(CsvBmlIngestionError):
    """The re-run cannot start (missing run, no table, wrong policy)."""

    code = "CBI_RERUN_REFUSED"


def rerun_rejects(factory: ConnectionFactory, workspace_id: int, run_id: str,
                  policy: OverflowPolicy = OverflowPolicy.REJECT) -> dict[str, Any]:
    """Re-insert the open rejected rows of ``run_id``; returns a summary dict.

    Raises:
        RerunError: unknown run (in this workspace), run has no table, table gone, or ``policy`` is ``fail``.
        TableProtectedError: the table is not owned by this workspace's pipeline.
    """
    if policy is OverflowPolicy.FAIL:
        raise RerunError("policy 'fail' makes no sense for a re-run; use 'reject' or 'truncate'")
    store = IssueStore(factory)
    run = store.get_run(workspace_id, run_id)
    if run is None:
        raise RerunError("run not found")
    if run["state"] == "superseded":
        raise RerunError("this run was superseded by a newer upload or re-run; its rejected rows are stale")
    table = run["table_name"]
    if not table or not _IDENT.match(table):
        raise RerunError("this run has no target table to re-run into")
    if not require_owned_or_absent(factory, table, workspace_owner(workspace_id)):
        raise RerunError(f"table {table!r} no longer exists; ingest the file again instead")
    limits = fetch_column_limits(factory, table)

    with factory() as conn:
        cur = conn.cursor()
        claimed = IssueStore.claim_open(cur, workspace_id, run_id)
        rerunnable: list[tuple[int, dict]] = []
        stuck: list[int] = []
        columns: list[str] | None = None
        for c in claimed:
            cols = (c["row"] or {}).get("columns") if isinstance(c["row"], dict) else None
            if isinstance(cols, dict) and cols and all(_IDENT.match(k) and k in limits for k in cols):
                columns = columns or list(cols)
                if list(cols) == columns:
                    rerunnable.append((c["reject_id"], cols))
                    continue
            stuck.append(c["reject_id"])

        inserted = 0
        report = OverflowReport()
        if rerunnable and columns:
            numbered = ((rid, tuple(vals[k] for k in columns) + (rid,)) for rid, vals in rerunnable)
            good = list(guard_numbered_rows(numbered, [*columns, _ID_COL], limits, policy, report, None))
            if good:
                sql = (f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})")
                cur.executemany(sql, [row[:-1] for row in good])
                IssueStore.mark_resolved(cur, workspace_id, [row[-1] for row in good])
                inserted = len(good)
            IssueStore.mark_still_open(cur, workspace_id, [(r.line_no, r.reason) for r in report.rejects.rows])
        if stuck:
            IssueStore.release(cur, workspace_id, stuck)
        run_state = IssueStore.finish_run_if_clean(cur, workspace_id, run_id) if claimed else run["state"]

    return {
        "run_id": run_id, "table": table, "attempted": len(claimed), "inserted": inserted,
        "truncated": report.rows_truncated, "still_rejected": report.rows_rejected,
        "not_rerunnable": len(stuck), "run_state": run_state if claimed else run["state"] or STATE_OPEN,
    }
