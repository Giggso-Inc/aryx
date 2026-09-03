"""Pure, patch-free helpers + the legacy metric-reader shim for data_api.py.

Split out of `api/data_api.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). Every name here is free of `get_settings`/`DatasourceStore`/
`JobStore`/`_source_purge_store`/`ports`/`datetime` dependencies — confirmed
via grep against `test_data_sources_api.py`, `test_xlsx_data_sources_api.py`,
and `test_source_pagination_api.py`'s whitebox patches before moving — so
none of those patches needed retargeting.
"""
from __future__ import annotations

import csv
import io
from collections import Counter
from typing import Any

from fastapi import HTTPException

from aryx import explore


class _LegacyMetricReader:
    """Compatibility reader used by lightweight unit-test stores only."""

    def __init__(self, store: object) -> None:
        self._store = store

    def source_record_counts(self) -> Counter[tuple[str, str]]:
        return _provenance_counts(list(self._store.list_members_provenance()))  # type: ignore[attr-defined]

    def source_entity_type_counts(
        self, _source_map: list[tuple[str, str, str]],
    ) -> dict[str, list[tuple[str, int]]]:
        return {}

    def source_edge_counts(
        self, source_map: list[tuple[str, str, str]],
    ) -> dict[str, int]:
        if not hasattr(self._store, "list_relationships"):
            return {}
        provenance = self._store.list_members_provenance()  # type: ignore[attr-defined]
        entity_sources = {
            (entity_id, system, dataset)
            for entity_id, system, dataset, _record_id in provenance
        }
        source_entities: dict[str, set[int]] = {}
        for source_key, system, dataset in source_map:
            source_entities.setdefault(source_key, set()).update(
                entity_id
                for entity_id, linked_system, linked_dataset in entity_sources
                if linked_system == system and linked_dataset == dataset
            )
        relationships = list(self._store.list_relationships())  # type: ignore[attr-defined]
        return {
            source_key: len({
                (source_id, target_id, name)
                for source_id, target_id, name in relationships
                if source_id in entity_ids or target_id in entity_ids
            })
            for source_key, entity_ids in source_entities.items()
        }

    def workspace_summary(self) -> dict:
        return explore.summarize(  # type: ignore[attr-defined]
            self._store.list_entities(), self._store.list_members_provenance(),
        )

    def source_records_page(
        self, system: str, dataset: str, *, limit: int, offset: int,
    ) -> tuple[int, list[dict]]:
        rows = self._store.list_source_payloads(system, dataset, limit=None)  # type: ignore[attr-defined]
        return len(rows), rows[offset:offset + limit]


def _catalog_item(catalog: list[dict], source_key: str) -> dict:
    item = next((row for row in catalog if row.get("source_key") == source_key), None)
    if item is None:
        raise HTTPException(404, "source not found")
    return item


def _is_generic_source_key(source_key: str) -> bool:
    return ":" in source_key and not source_key.startswith(("xml:", "xlsx:", "legacy-xml:", "ds:"))


def _parse_generic_source_key(source_key: str) -> tuple[str, str]:
    if not _is_generic_source_key(source_key):
        raise HTTPException(404, "source not found")
    source_system, source_dataset = source_key.split(":", 1)
    if not source_system or not source_dataset:
        raise HTTPException(404, "source not found")
    return source_system, source_dataset


def _provenance_counts(
    provenance: list[tuple[int, str, str, str]] | tuple[tuple[int, str, str, str], ...],
) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for _entity_id, system, dataset, _record_id in provenance:
        counts[(system, dataset)] += 1
    return counts


def _csv_response_bytes(payload_rows: list[dict]) -> bytes:
    headers: list[str] = []
    for row in payload_rows:
        for key in row.keys():
            text_key = str(key)
            if text_key not in headers:
                headers.append(text_key)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()
    for row in payload_rows:
        writer.writerow({
            header: "" if row.get(header) is None else str(row.get(header))
            for header in headers
        })
    return buffer.getvalue().encode("utf-8")


def _asset_matches(asset: dict, asset_key: str) -> bool:
    return (asset.get("asset_key") or asset.get("filename")) == asset_key
