"""Document-discovery pipeline package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_consolidate_csv_names": "doc_discovery_csv",
    "_detect_fk_links": "doc_discovery_fk",
    "_detect_fk_links_workspace": "doc_discovery_fk",
    "_detect_script_data_flow_links": "doc_discovery_fk",
    "_guess_key_col": "doc_discovery_types",
    "_id_like_names": "doc_discovery_types",
    "_id_priority_mk": "doc_discovery_types",
    "_infer_type": "doc_discovery_types",
    "_key_suffixes": "doc_discovery_types",
    "_name_like_names": "doc_discovery_types",
    "_persist_tabular_sources": "doc_discovery_persist",
    "_sheet_slug": "doc_discovery_xlsx",
    "_singular": "doc_discovery_types",
    "_stem_type": "doc_discovery_types",
    "_update_confirm_state": "doc_discovery",
    "_xlsx_to_csvs": "doc_discovery_xlsx",
    "_xml_to_csvs": "doc_discovery_xml",
    "ingest_confirmed": "doc_discovery",
    "read_files": "doc_discovery",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.pipeline.doc_discovery.{mod_name}")
    return getattr(mod, name)
