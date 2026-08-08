"""Regression coverage for migrate.py's post-migration constraint checks.

Raven review finding on PR #9: a RAISE from inside a migration's own DO
block is caught and logged as a warning by apply_migrations()'s generic
per-statement error handling, same as any other statement failure — so it
never actually stops startup on schema drift. _verify_critical_constraints()
runs after the per-statement loop and raises a plain RuntimeError (not
psycopg.Error), which is not caught anywhere in this module, so it always
propagates to the caller.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

# Stub heavy deps so aryx.store.migrate loads without installed DB packages
# (mirrors the stub list in test_job_store.py).
sys.modules.setdefault("psycopg", MagicMock(Error=Exception))
for _mod in ("psycopg.types", "psycopg.types.json",
             "falkordb", "pgvector", "pgvector.psycopg"):
    sys.modules.setdefault(_mod, MagicMock())
sys.modules.setdefault("psycopg_pool", MagicMock(ConnectionPool=MagicMock()))

import pytest

from aryx.store.migrate import _verify_critical_constraints


def _mock_conn(fetchone_results: list) -> MagicMock:
    """A connection whose cursor().fetchone() yields each result in order."""
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = fetchone_results
    return conn


def test_passes_when_every_constraint_matches_expected_definition():
    conn = _mock_conn([
        ("UNIQUE (workspace_id, name)",),
        ("FOREIGN KEY (workspace_id, parent_type) REFERENCES aryx_ontology_type"
         "(workspace_id, name) ON UPDATE CASCADE ON DELETE SET NULL",),
    ])
    _verify_critical_constraints(conn)  # must not raise


def test_raises_when_constraint_is_missing():
    conn = _mock_conn([None])
    with pytest.raises(RuntimeError, match="missing"):
        _verify_critical_constraints(conn)


def test_raises_when_constraint_definition_has_drifted():
    conn = _mock_conn([("UNIQUE (name)",)])
    with pytest.raises(RuntimeError, match="schema drift"):
        _verify_critical_constraints(conn)
