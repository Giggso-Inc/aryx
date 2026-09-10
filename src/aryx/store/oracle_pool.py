"""Oracle ADB 23ai connection pool — psycopg3-compatible interface layer.

Wraps python-oracledb so all 19 store classes work unchanged when
ARYX_DB_BACKEND=oci. The wrapper handles three translation concerns:

1. Parameter style: psycopg3 uses %s / %(name)s — oracledb uses :1 / :name
2. JSON: psycopg3 uses psycopg.types.json.Json() wrappers — oracledb accepts
   plain dicts for JSON columns natively on ADB 23ai
3. RETURNING: psycopg3 returns rows from INSERT/UPDATE RETURNING via fetchone();
   oracledb requires cursor.var() output variables and RETURNING ... INTO :var

All OCI/oracledb imports are inside function bodies — local deployments that
don't have oracledb installed never hit this module.

As of the Raven Style Compliance Plan's Phase 2a (2026-09-03), this module
is a thin re-export hub over 5 focused sibling modules -- the actual logic
lives in `store.oracle_sql_translate`, `store.oracle_param_coerce`,
`store.oracle_clob`, `store.oracle_cursor`, and
`store.oracle_connection_pool`. Every name below is re-exported so every
existing caller (`store.oracle_workspace`, `store.pool`, `graph.
oracle_graph_reader`, `graph.oracle_graph_store`, `cpq.rdb`, and the test
suite's direct `oracle_pool.<name>` attribute access/patching) keeps
working unchanged. Import from the specific sibling module directly in new
code -- this file exists for backward compatibility, not as the place to
add new logic.
"""
from __future__ import annotations

from aryx.store.oracle_clob import _coerce_clob, _hint_clob, _hint_clob_many
from aryx.store.oracle_connection_pool import (
    OracleConnectionWrapper,
    OraclePool,
    close_all_oracle,
    get_oracle_pool,
)
from aryx.store.oracle_cursor import OracleCursorWrapper
from aryx.store.oracle_param_coerce import (
    _read_lob,
    _restore_empty_string,
    _strip_sql_comments,
    _tuple_seq_to_dict,
    _unwrap_params,
)
from aryx.store.oracle_sql_translate import _BIND_NAME_RE, _MERGE_ON_RE, _translate_sql

__all__ = [
    "OracleConnectionWrapper",
    "OracleCursorWrapper",
    "OraclePool",
    "close_all_oracle",
    "get_oracle_pool",
]
