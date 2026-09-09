"""CPQ relational-database (RDB) source package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "OracleCpqRdb": "rdb_oracle",
    "PostgresCpqRdb": "rdb_postgres",
    "_as_attrs": "rdb_helpers",
    "_as_int": "rdb_helpers",
    "_type_pattern": "rdb_helpers",
    "get_cpq_rdb": "rdb",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.rdb.{mod_name}")
    return getattr(mod, name)
