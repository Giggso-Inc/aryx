"""XML-aware source catalog helpers for the Data tab.

As of the Raven Style Compliance Plan's Phase 2a (2026-09-03), this module
is a pure re-export hub: pure meta-extraction helpers live in
`source_catalog_meta`, config-builder/upsert/find helpers live in
`source_catalog_upsert`, read-side catalog/detail builders live in
`source_catalog_detail`, and soft-delete/download-payload helpers live in
`source_catalog_delete_download`. Every importer across the codebase uses
direct-name imports with zero whitebox patches on this module — confirmed
via grep before splitting — so this re-export list is the only
compatibility surface needed.
"""
from __future__ import annotations

from aryx.source.source_catalog_delete_download import (
    mark_xlsx_asset_deleted,
    mark_xlsx_source_deleted,
    mark_xml_asset_deleted,
    mark_xml_source_deleted,
    xlsx_download_payload,
    xml_download_payload,
)
from aryx.source.source_catalog_detail import (
    build_source_catalog,
    build_source_catalog_from_counts,
    build_source_detail,
    build_source_detail_from_counts,
)
from aryx.source.source_catalog_meta import _display_kind, source_actions
from aryx.source.source_catalog_upsert import (
    find_generic_source_row,
    find_legacy_xml_row,
    generic_catalog_config,
    legacy_xml_catalog_config,
    legacy_xml_row,
    restore_generic_source_entry,
    upsert_generic_source_entry,
    upsert_legacy_xml_catalog_entry,
    upsert_xlsx_catalog_entry,
    upsert_xml_catalog_entry,
    xlsx_asset_record,
    xlsx_catalog_config,
    xml_asset_record,
    xml_catalog_config,
)

__all__ = [
    "_display_kind",
    "build_source_catalog",
    "build_source_catalog_from_counts",
    "build_source_detail",
    "build_source_detail_from_counts",
    "find_generic_source_row",
    "find_legacy_xml_row",
    "generic_catalog_config",
    "legacy_xml_catalog_config",
    "legacy_xml_row",
    "mark_xlsx_asset_deleted",
    "mark_xlsx_source_deleted",
    "mark_xml_asset_deleted",
    "mark_xml_source_deleted",
    "restore_generic_source_entry",
    "source_actions",
    "upsert_generic_source_entry",
    "upsert_legacy_xml_catalog_entry",
    "upsert_xlsx_catalog_entry",
    "upsert_xml_catalog_entry",
    "xlsx_asset_record",
    "xlsx_catalog_config",
    "xlsx_download_payload",
    "xml_asset_record",
    "xml_catalog_config",
    "xml_download_payload",
]
