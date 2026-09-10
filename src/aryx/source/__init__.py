"""Source-catalog metadata/metrics package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_active_assets": "source_catalog_meta",
    "_asset_rows": "source_catalog_meta",
    "_build_meta_source_detail": "source_catalog_detail",
    "_csv_bytes_from_payload_rows": "source_catalog_meta",
    "_display_kind": "source_catalog_meta",
    "_generic_meta": "source_catalog_meta",
    "_legacy_groups": "source_catalog_meta",
    "_matches": "source_metrics",
    "_parent_datasets": "source_metrics",
    "_parent_references": "source_metrics",
    "_preview_payload_rows": "source_catalog_meta",
    "_preview_rows": "source_catalog_meta",
    "_source_counts": "source_catalog_meta",
    "_xlsx_meta": "source_catalog_meta",
    "_xml_meta": "source_catalog_meta",
    "apply_source_metrics": "source_metrics",
    "build_source_catalog": "source_catalog_detail",
    "build_source_catalog_from_counts": "source_catalog_detail",
    "build_source_detail": "source_catalog_detail",
    "build_source_detail_from_counts": "source_catalog_detail",
    "find_generic_source_row": "source_catalog_upsert",
    "find_legacy_xml_row": "source_catalog_upsert",
    "generic_catalog_config": "source_catalog_upsert",
    "legacy_xml_catalog_config": "source_catalog_upsert",
    "legacy_xml_row": "source_catalog_upsert",
    "mapped_references": "source_metrics",
    "mark_xlsx_asset_deleted": "source_catalog_delete_download",
    "mark_xlsx_source_deleted": "source_catalog_delete_download",
    "mark_xml_asset_deleted": "source_catalog_delete_download",
    "mark_xml_source_deleted": "source_catalog_delete_download",
    "page_source_catalog": "source_metrics",
    "restore_generic_source_entry": "source_catalog_upsert",
    "source_actions": "source_catalog_meta",
    "source_references": "source_metrics",
    "upsert_generic_source_entry": "source_catalog_upsert",
    "upsert_legacy_xml_catalog_entry": "source_catalog_upsert",
    "upsert_xlsx_catalog_entry": "source_catalog_upsert",
    "upsert_xml_catalog_entry": "source_catalog_upsert",
    "xlsx_asset_record": "source_catalog_upsert",
    "xlsx_catalog_config": "source_catalog_upsert",
    "xlsx_download_payload": "source_catalog_delete_download",
    "xml_asset_record": "source_catalog_upsert",
    "xml_catalog_config": "source_catalog_upsert",
    "xml_download_payload": "source_catalog_delete_download",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.source.{mod_name}")
    return getattr(mod, name)
