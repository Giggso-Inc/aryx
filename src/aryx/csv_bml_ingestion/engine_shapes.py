"""Which CSVs the CPQ engine reads as Data Tables, whether or not a script queries them.

The CSV pipeline loads a CSV into its ``ws<id>_<stem>`` table only when some script in the XML reads that table
(the schema is authored from those queries). The engine reads a few tables nobody queries from a script: the
platform uses them itself (``BaseModelToConfig`` maps a device name such as "APX 3000" to its CPQ model, so
without it model resolution falls back to a fixed product). This module answers "does the engine read a table
with these columns?" from the engine's own shape tests, so the pipeline can still load such a table (see
``sql_author.author_sql_from_layout``). No table or product name appears here; only the engine's shapes decide.
"""
from __future__ import annotations

import os

LOAD_ENGINE_TABLES_ENV = "ARYX_CSV_BML_LOAD_ENGINE_TABLES"
_FALSE = {"0", "false", "no", "off"}


def load_engine_tables_enabled() -> bool:
    """On by default; ``ARYX_CSV_BML_LOAD_ENGINE_TABLES=false`` restores the old "no script reads it -> skip"."""
    return os.environ.get(LOAD_ENGINE_TABLES_ENV, "").strip().lower() not in _FALSE


def engine_shape_of_columns(columns: tuple[str, ...] | list[str]) -> str | None:
    """Name of the engine Data Table shape ``columns`` satisfy, or None when the engine never reads such a table.

    ``columns`` are the SQL column names (lower case). The engine reads a workspace table through
    ``recase`` (``cpqmodel`` -> ``cpqModel``), and a name can have two spellings, so both are tried, exactly as the
    reader does. Lazy imports: the engine package imports this one.
    """
    from aryx.cpq.data_table.data_table_inference import _is_basemodel_to_config_shaped  # noqa: PLC0415
    from aryx.cpq.data_table.data_table_shapes import _detect_shape  # noqa: PLC0415
    from aryx.cpq.rdb.rdb_workspace_tables import recase  # noqa: PLC0415

    for variant in (0, 1):
        keys = {recase(column, variant) for column in columns}
        shape = _detect_shape(keys)
        if shape:
            return shape
        if _is_basemodel_to_config_shaped(keys):
            return "basemodel_to_config"
    return None
