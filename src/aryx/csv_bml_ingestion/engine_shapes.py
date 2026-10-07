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


# Two of the engine's standalone shapes are loose as the engine defines them: country region is just countryCode +
# region, default-in-attr is BaseModel + attr1 + val1 with no model column. A customer CSV with those columns would
# be loaded and then read by the engine as geo / default data, so for the script-free path they must also carry the
# distinguishing columns of the real tables (newCountryRegion has countryDesc and emsParent; defaultInAttr has
# PartNumber and Qty). The engine's own detectors are unchanged.
_LOOSE_SHAPE_EXTRA_COLUMNS: dict[str, frozenset[str]] = {
    "country_region": frozenset({"countrydesc", "emsparent"}),
    "defaultinattr": frozenset({"partnumber", "qty"}),
}


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
    # reads through its own standalone loaders (base model, attr-var mapping, country region, default-in-attr, RTTE/TA)
    standalone = (
        ("basemodel_to_config", _is_basemodel_to_config_shaped),
        ("attr_var_mapping", shapes._is_attr_var_mapping_shaped),
        ("defaultinattr", shapes._is_defaultinattr_shaped),
        ("country_region", shapes._is_country_region_shaped),
        ("rtte_ta", shapes._is_rtte_ta_shaped),
    )
    lowered = {str(column).lower() for column in columns}
    for variant in (0, 1):
        keys = {recase(column, variant) for column in columns}
        shape = shapes._detect_shape(keys)
        if shape:
            return shape
        for name, detector in standalone:
            if detector(keys) and _LOOSE_SHAPE_EXTRA_COLUMNS.get(name, frozenset()) <= lowered:
                return name
    return None
