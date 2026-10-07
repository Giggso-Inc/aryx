"""Which CSVs the CPQ engine reads as Data Tables, whether or not a script queries them.

The CSV pipeline loads a CSV into its ``ws<id>_<stem>`` table only when some script in the XML reads that table
(the schema is authored from those queries). The engine reads a few tables nobody queries from a script: the
platform uses them itself (``BaseModelToConfig`` maps a device name such as "APX 3000" to its CPQ model, so
without it model resolution falls back to a fixed product). This module answers "does the engine read a table
with these columns?" from the engine's own shape tests, so the pipeline can still load such a table (see
``sql_author.author_sql_from_layout``). No table or product name appears here; only the engine's shapes decide.
"""
from __future__ import annotations

from aryx.csv_bml_ingestion.config import LOAD_ENGINE_TABLES_ENV, load_engine_tables_enabled

__all__ = ["LOAD_ENGINE_TABLES_ENV", "engine_shape_of_columns", "load_engine_tables_enabled"]


def engine_shape_of_columns(columns: tuple[str, ...] | list[str]) -> str | None:
    """Name of the engine Data Table shape ``columns`` satisfy, or None when the engine never reads such a table.

    ``columns`` are the SQL column names (lower case). The engine reads a workspace table through
    ``recase`` (``cpqmodel`` -> ``cpqModel``), and a name can have two spellings, so both are tried, exactly as the
    reader does. Lazy imports: the engine package imports this one.
    """
    from aryx.cpq.data_table import data_table_shapes as shapes  # noqa: PLC0415
    from aryx.cpq.data_table.data_table_inference import _is_basemodel_to_config_shaped  # noqa: PLC0415
    from aryx.cpq.rdb.rdb_workspace_tables import recase  # noqa: PLC0415

    # the pooled shapes first (sequence, series mapping, region rule, constraint, hierarchy), then the ones the engine
    # reads through its own standalone loaders that need several specific columns (base model, attr-var mapping,
    # RTTE/TA). NOT included: `_is_country_region_shaped` (just countryCode + region) and `_is_defaultinattr_shaped`
    # (BaseModel + attr1 + val1, no model column) are too loose to create a table from: an unrelated customer CSV
    # with those columns would be loaded and then read by the engine as geo / default data. Those two tables are
    # read by scripts in practice, so they still load through the script path exactly as before.
    standalone = (
        ("basemodel_to_config", _is_basemodel_to_config_shaped),
        ("attr_var_mapping", shapes._is_attr_var_mapping_shaped),
        ("rtte_ta", shapes._is_rtte_ta_shaped),
    )
    for variant in (0, 1):
        keys = {recase(column, variant) for column in columns}
        shape = shapes._detect_shape(keys)
        if shape:
            return shape
        for name, detector in standalone:
            if detector(keys):
                return name
    return None
