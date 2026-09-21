"""Backend-agnostic RDB access for the CPQ engine (Postgres + Oracle ADB).

The CPQ engine reads entity attributes and rule definitions from the
relational store. Postgres stores them in a JSONB column queried with
``attributes->>'key'``; Oracle ADB 26ai stores a JSON column queried with
``JSON_VALUE(attributes, '$.key')``. This module hides that dialect split so
no raw backend-specific SQL lives in ``cpq/``.

All methods return plain Python data; JSON decoding and type coercion happen
here. Failures are logged and surface as empty results — the CPQ engine
treats missing rule data as "no rules", never as a hard error.

As of the Raven Style Compliance Plan's Phase 2a (2026-09-03), the shared
coercion/pattern helpers live in `cpq.rdb_helpers`, the Postgres
implementation lives in `cpq.rdb_postgres`, and the Oracle implementation
(a subclass of the Postgres one) lives in `cpq.rdb_oracle` — all re-imported
here since every importer across the codebase (`engine.py`, `rule_export.py`,
`data_table_loader.py`, both test files) uses direct-name imports with zero
whitebox patches on this module.
"""
from __future__ import annotations

from aryx.config import get_settings
from aryx.cpq.rdb.rdb_oracle import OracleCpqRdb
from aryx.cpq.rdb.rdb_postgres import PostgresCpqRdb

__all__ = [
    "OracleCpqRdb",
    "PostgresCpqRdb",
    "get_cpq_rdb",
]


def get_cpq_rdb() -> PostgresCpqRdb:
    """Return the RDB accessor matching the configured backend."""
    if get_settings().effective_db_backend() == "oci":
        return OracleCpqRdb()
    return PostgresCpqRdb()
