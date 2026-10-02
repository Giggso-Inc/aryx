"""Run options and result types shared by the pipeline modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from aryx.csv_bml_ingestion import constants as C
from aryx.csv_bml_ingestion.overflow import OverflowPolicy
from aryx.csv_bml_ingestion.rejects import RejectedRow
from aryx.csv_bml_ingestion.sql_author import Completer


@dataclass(frozen=True, slots=True)
class IngestOptions:
    """Knobs for one ingestion run."""

    replace: bool = True                          # delete existing rows first (full refresh)
    batch_size: int = C.DEFAULT_BATCH_SIZE
    sql_root: Path | None = None                  # None = constants.default_sql_root()
    overflow: OverflowPolicy = OverflowPolicy.REJECT
    rejects_dir: Path | None = None               # default: next to the CSV file
    sql_author: Completer | None = None           # None = never author SQL; missing files then fail
    owner: str = C.OWNER_TAG                      # ownership tag a table must carry to be loaded into
    physical_table: Callable[[str], str] | None = None   # logical name -> Oracle table (None = same name)


@dataclass(slots=True)
class IngestResult:
    """Outcome of one CSV."""

    source: str
    status: str = "failed"          # loaded | skipped | failed
    table: str | None = None        # logical name: the CSV file's stem (what the BML queries say)
    physical_table: str = ""        # the Oracle table actually used (== table unless per-workspace naming)
    rows_loaded: int = 0
    rows_bad: int = 0               # malformed (wrong width / unparsable integer)
    rows_rejected: int = 0          # did not fit their column (policy=reject)
    rows_truncated: int = 0         # loaded after text was cut to fit (policy=truncate)
    rejects_file: str = ""
    error_code: str = ""
    message: str = ""
    bml_scripts: list[str] = field(default_factory=list)
    reject_rows: list[RejectedRow] = field(default_factory=list)   # rows not loaded, for storage / re-run
    reject_total: int = 0                                          # true count (list is capped)
    run_id: str = ""                                                # set when the run was stored
