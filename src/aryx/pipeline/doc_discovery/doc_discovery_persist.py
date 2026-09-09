"""Parent-workbook source-catalog persistence for confirmed tabular plans.

Split out of `pipeline/doc_discovery.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03). Directly whitebox-patched (`aryx.pipeline.doc_
discovery._persist_tabular_sources`) — its only caller, `ingest_confirmed`,
stays in `doc_discovery.py` and imports it from here, so the patch keeps
intercepting it unchanged.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from aryx.source.source_catalog import (
    upsert_xlsx_catalog_entry,
    upsert_xml_catalog_entry,
    xlsx_asset_record,
    xml_asset_record,
)
from aryx.store.datasource_store import DatasourceStore


def _persist_tabular_sources(valid_plans: list[dict[str, Any]], workspace_id: int, dsn: str) -> None:
    """Persist parent-workbook metadata for the source catalog.

    Every confirmed plan derived from an XML or XLSX upload carries its
    original source_filename/source_bytes (set in read_files() for both
    suffixes alike — see converted_tabular above). The catalog entry kind
    must match the ORIGINAL file's own suffix, not always "xml": writing
    every source as an xml catalog entry mislabeled .xlsx uploads as
    "XML File" in the Data tab and left their generated-asset metadata
    under the wrong catalog key.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for plan in valid_plans:
        source_filename = plan.get("source_filename")
        source_bytes = plan.get("source_bytes")
        if not source_filename or source_bytes is None:
            continue
        group = grouped.setdefault(
            source_filename, {"source_bytes": source_bytes, "assets": []},
        )
        is_xlsx = Path(source_filename).suffix.lower() == ".xlsx"
        asset_record = xlsx_asset_record if is_xlsx else xml_asset_record
        group["assets"].append(asset_record(
            filename=plan["filename"],
            dataset=Path(plan["filename"]).stem,
            ontology_type=plan["ontology_type"],
            content_bytes=plan["data"],
        ))
    if not grouped:
        return
    store = DatasourceStore(dsn)
    for source_filename, payload in grouped.items():
        if Path(source_filename).suffix.lower() == ".xlsx":
            upsert_xlsx_catalog_entry(
                store,
                workspace_id=workspace_id,
                source_filename=source_filename,
                xlsx_bytes=payload["source_bytes"],
                assets=payload["assets"],
            )
        else:
            upsert_xml_catalog_entry(
                store,
                workspace_id=workspace_id,
                source_filename=source_filename,
                xml_bytes=payload["source_bytes"],
                assets=payload["assets"],
            )
