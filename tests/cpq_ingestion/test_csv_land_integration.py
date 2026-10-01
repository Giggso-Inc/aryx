"""Live integration test — real Postgres (or Oracle ADB, via ARYX_DB_BACKEND
=oci + ARYX_RDB_DSN pointed at it), no mocks.

Skipped by default, same opt-in convention as test_pipeline_integration.py:

    ARYX_RUN_LOCAL_INTEGRATION_TESTS=1 ARYX_RDB_DSN=postgresql://... \\
        pytest tests/cpq_ingestion/test_csv_land_integration.py -v

Exercises land_csv_directly() against a real landing store, proving the
workspace-isolation edge case the user explicitly called out: two
workspaces landing CSV data through the SAME database/ADB instance must
never see each other's rows, even when the source filename/stem is
identical between them (the realistic case: two tenants both upload a file
named "catalog.csv").
"""
from __future__ import annotations

import os

import pytest

from aryx.config import get_settings

pytestmark = pytest.mark.skipif(
    os.environ.get("ARYX_RUN_LOCAL_INTEGRATION_TESTS") != "1",
    reason="opt-in: set ARYX_RUN_LOCAL_INTEGRATION_TESTS=1 with a live Postgres/Oracle ADB reachable",
)

CSV_A = b"id,name\n1,Widget A\n2,Widget B\n"
CSV_B = b"id,name\n1,Gadget X\n2,Gadget Y\n3,Gadget Z\n"


def test_two_workspaces_landing_the_same_filename_stay_isolated():
    from aryx.cpq_ingestion.csv_land import land_csv_directly
    from aryx.store.postgres_store import PostgresStore

    dsn = get_settings().effective_dsn()
    workspace_a = 999_101  # dedicated, disposable test workspace ids
    workspace_b = 999_102

    result_a = land_csv_directly(CSV_A, "catalog", workspace_id=workspace_a, dsn=dsn)
    result_b = land_csv_directly(CSV_B, "catalog", workspace_id=workspace_b, dsn=dsn)

    # Same source_key ("catalog") in both workspaces -- isolation must come
    # from workspace_id scoping alone, not from any filename-based trick.
    assert result_a["rows_landed"] == 2
    assert result_b["rows_landed"] == 3

    store_a = PostgresStore(dsn, workspace_a)
    store_b = PostgresStore(dsn, workspace_b)

    # Workspace A's own store must report ONLY its own run's row count --
    # asking it about workspace B's run_id must not leak workspace B's rows.
    assert store_a.count_landed(result_a["run_id"]) == 2
    assert store_a.count_landed(result_b["run_id"]) == 0
    assert store_b.count_landed(result_b["run_id"]) == 3
    assert store_b.count_landed(result_a["run_id"]) == 0
