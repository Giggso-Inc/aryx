"""Constants shared across the csv_bml_ingestion package."""
from __future__ import annotations

import os
from pathlib import Path

# Pipeline step names — also the Raven ``context["step"]`` values, so a log
# search for one step name shows exactly where a run got to.
STEP_TABLE_NAME = "1_extract_table_name"
STEP_BML_LOOKUP = "2_identify_bml_query"
STEP_AUTHOR_SQL = "3a_author_sql"
STEP_SQL_ARTIFACTS = "3_load_sql_artifacts"
STEP_APPLY_SCHEMA = "3b_apply_schema_and_indexes"
STEP_CSV_INGEST = "4_csv_ingestion"
STEP_RUN = "run"

# Where the LLM-authored schema/index files live (human-readable reference, saved
# at first ingest of a table): <root>/<lowercase table name>/{schema,indexes}.sql
SQL_DIR_ENV = "ARYX_CSV_BML_SQL_DIR"
_DEFAULT_SQL_ROOT = Path(__file__).resolve().parent / "sql"


def default_sql_root() -> Path:
    """Where authored SQL is read from / saved to: ``ARYX_CSV_BML_SQL_DIR`` or the package ``sql/`` folder."""
    override = os.environ.get(SQL_DIR_ENV, "").strip()
    return Path(override) if override else _DEFAULT_SQL_ROOT
SCHEMA_FILE = "schema.sql"
INDEXES_FILE = "indexes.sql"
BML_SOURCE_FILE = "bml_source.md"

# Safe SQL identifier (the table name comes from a filename, so it is
# validated before it is ever interpolated into DDL/DML).
TABLE_NAME_RE = r"^[a-z][a-z0-9_]{0,62}$"  # ADB identifiers allow 128; stay well inside it

# A table named after an uploaded file must never be an application or system table. The allowed
# names come from the (user-supplied) XML, so these are refused outright, whatever the XML says.
DENIED_TABLE_PREFIXES = ("aryx_", "gg_", "cpq_", "sys_", "dba_", "all_", "user_", "cdb_", "mdsys", "ctxsys", "ords_")
DENIED_TABLE_NAMES = frozenset({"dual", "sys", "system", "public"})

# Ownership marker kept as the table's COMMENT: only tables carrying it are ever deleted from / loaded.
OWNER_TAG = "csv_bml_ingestion"

CSV_META_START = "_start meta data"
CSV_META_END = "_end meta data"

DEFAULT_BATCH_SIZE = 500

# Raven-log service tag for this pipeline.
RAVEN_COMPONENT = "csv_bml_ingestion"

# Raven error code for step 2 falling back from the curated graph to the raw graph.
CURATED_FALLBACK_CODE = "CBI_CURATED_EMPTY_FALLBACK"

# Raven error code for step 2 falling back from the curated graph to the raw graph.
CURATED_FALLBACK_CODE = "CBI_CURATED_EMPTY_FALLBACK"

# Oracle reserved words that can plausibly appear as CSV headers. A header
# that lowercases to one of these gets the ``_col`` suffix (see
# ``csv_reader.to_column_name``); the SQL files must follow the same rule.
ORACLE_RESERVED = frozenset({
    "access", "add", "all", "alter", "and", "any", "as", "asc", "audit", "between", "by",
    "char", "check", "cluster", "column", "comment", "compress", "connect", "create",
    "current", "date", "decimal", "default", "delete", "desc", "distinct", "drop", "else",
    "exclusive", "exists", "file", "float", "for", "from", "grant", "group", "having",
    "identified", "immediate", "in", "increment", "index", "initial", "insert", "integer",
    "intersect", "into", "is", "level", "like", "lock", "long", "maxextents", "minus",
    "mlslabel", "mode", "modify", "noaudit", "nocompress", "not", "nowait", "null", "number",
    "of", "offline", "on", "online", "option", "or", "order", "pctfree", "prior", "public",
    "raw", "rename", "resource", "revoke", "row", "rowid", "rownum", "rows", "select",
    "session", "set", "share", "size", "smallint", "start", "successful", "synonym",
    "sysdate", "table", "then", "to", "trigger", "uid", "union", "unique", "update", "user",
    "validate", "values", "varchar", "varchar2", "view", "whenever", "where", "with",
})
