"""Data Explorer API (v2) — the transparency surface over resolved entities.

Reads the relational source of truth (EntityStore) so every row carries its
golden-record attributes and the source records it traces back to. Pure shaping
lives in aryx.explore; this module is the thin HTTP wire.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from aryx import explore
from aryx.config import get_settings
from aryx.source_catalog import (
    build_source_catalog_from_counts,
    build_source_detail_from_counts,
    find_legacy_xml_row,
    legacy_xml_row,
    mark_xlsx_asset_deleted,
    mark_xlsx_source_deleted,
    mark_xml_asset_deleted,
    mark_xml_source_deleted,
    upsert_generic_source_entry,
    upsert_legacy_xml_catalog_entry,
    xlsx_download_payload,
    xml_download_payload,
)
from aryx.source_metrics import (
    apply_source_metrics,
    mapped_references,
    page_source_catalog,
    source_references,
)
from aryx.store.entity_store import EntityStore
from aryx.store.datasource_store import DatasourceStore
from aryx.store.job_store import JobStore
from aryx.store.source_metrics_store import SourceMetricsStore

logger = logging.getLogger(__name__)
_DATETIME_TYPE = datetime
_SOURCE_PAGE_SIZE = 50
_ENTITY_TYPE_PAGE_SIZE = 50
_RECORD_PAGE_SIZE = 25


class FkLink(BaseModel):
    source_type: str
    source_attr: str
    target_type: str
    target_attr: str
    name: str


class RelateRequest(BaseModel):
    workspace_id: int = 1
    links: list[FkLink] = []
    replace: bool = True
    reproject: bool = True


def _store(workspace_id: int) -> EntityStore:
    return EntityStore(get_settings().rdb_dsn, workspace_id)


def _datasource_store() -> DatasourceStore:
    return DatasourceStore(get_settings().rdb_dsn)


def _job_store() -> JobStore:
    return JobStore(get_settings().rdb_dsn)


def _metrics_store(workspace_id: int) -> SourceMetricsStore:
    return SourceMetricsStore(get_settings().rdb_dsn, workspace_id)


def data_router() -> APIRouter:
    router = APIRouter(prefix="/data")

    @router.get("/summary")
    def summary(workspace_id: int = 1) -> dict:
        """Type counts, source breakdown, and the dedup story."""
        store = _store(workspace_id)
        try:
            return _metric_reader(store, workspace_id).workspace_summary()
        except Exception as exc:  # noqa: BLE001 — surface to the Data UI
            logger.warning("data summary failed: %s", exc)
            return {"error": f"data unavailable: {exc}"}
        finally:
            store.close()

    @router.get("/entities")
    def entities(workspace_id: int = 1, type: str | None = None,
                 limit: int = 50, offset: int = 0) -> dict:
        """Entities (optionally by type) with attributes + provenance."""
        store = _store(workspace_id)
        try:
            return explore.entities_view(
                store.list_entities(), store.list_members_provenance(),
                ontology_type=type, limit=limit, offset=offset)
        except Exception as exc:  # noqa: BLE001
            logger.warning("data entities failed: %s", exc)
            return {"error": f"data unavailable: {exc}", "items": []}

    @router.get("/graph")
    def graph(workspace_id: int = 1) -> dict:
        """Type-level knowledge map: nodes per type, edges aggregated by relation."""
        store = _store(workspace_id)
        try:
            return explore.graph_view(store.list_entities(),
                                      store.list_relationships())
        except Exception as exc:  # noqa: BLE001
            logger.warning("data graph failed: %s", exc)
            return {"error": f"graph unavailable: {exc}",
                    "type_nodes": [], "type_edges": []}

    @router.get("/sources")
    def sources(workspace_id: int = 1) -> list[dict]:
        """Return the backward-compatible unpaged source catalog."""
        store = _store(workspace_id)
        try:
            reader, datasources, counts, catalog = _catalog_snapshot(store, workspace_id)
            refs = mapped_references(catalog, datasources, counts)
            return apply_source_metrics(catalog, reader.source_entity_type_counts(refs))
        except Exception as exc:  # noqa: BLE001
            logger.warning("data sources failed: %s", exc)
            return []
        finally:
            store.close()

    @router.get("/sources/page")
    def sources_page(
        workspace_id: int = 1,
        page: int = Query(1, ge=1),
        q: str = Query("", max_length=200),
        category: Literal["all", "database", "documents", "api"] = "all",
    ) -> dict:
        """Return a server-filtered, bounded source catalog page."""
        store = _store(workspace_id)
        try:
            reader, datasources, counts, catalog = _catalog_snapshot(store, workspace_id)
            result = page_source_catalog(
                catalog, query=q, category=category, page=page, page_size=_SOURCE_PAGE_SIZE,
            )
            refs = mapped_references(result["items"], datasources, counts)
            result["items"] = apply_source_metrics(
                result["items"], reader.source_entity_type_counts(refs),
            )
            return result
        finally:
            store.close()

    @router.get("/sources/{source_key}")
    def source_detail(source_key: str, workspace_id: int = 1) -> dict:
        """Return a universal in-tab detail payload for any catalog source."""
        store = _store(workspace_id)
        try:
            reader, datasources, counts, catalog = _catalog_snapshot(store, workspace_id)
            item = _catalog_item(catalog, source_key)
            refs = source_references(source_key, datasources, counts)
            stats = reader.source_entity_type_counts(
                [(source_key, system, dataset) for system, dataset in refs],
            ).get(source_key, [])
            return _universal_source_detail(store, item, datasources, counts, stats)
        finally:
            store.close()

    @router.get("/sources/{source_key:path}/entity-types")
    def source_entity_types(
        source_key: str,
        workspace_id: int = 1,
        page: int = Query(1, ge=1),
        q: str = Query("", max_length=200),
    ) -> dict:
        """Return a searchable page of entity types for one logical source."""
        store = _store(workspace_id)
        try:
            reader, datasources, counts, catalog = _catalog_snapshot(store, workspace_id)
            _catalog_item(catalog, source_key)
            refs = source_references(source_key, datasources, counts)
            types = reader.source_entity_type_counts(
                [(source_key, system, dataset) for system, dataset in refs],
            ).get(source_key, [])
            needle = q.strip().lower()
            items = [{"name": name, "count": count} for name, count in types if needle in name.lower()]
            start = (page - 1) * _ENTITY_TYPE_PAGE_SIZE
            return {"items": items[start:start + _ENTITY_TYPE_PAGE_SIZE], "total": len(items),
                    "page": page, "page_size": _ENTITY_TYPE_PAGE_SIZE}
        finally:
            store.close()

    @router.get("/sources/{source_key:path}/records")
    def source_records(
        source_key: str,
        workspace_id: int = 1,
        page: int = Query(1, ge=1),
    ) -> dict:
        """Return a bounded landed-record preview for a generic source."""
        store = _store(workspace_id)
        try:
            reader, datasources, counts, catalog = _catalog_snapshot(store, workspace_id)
            _catalog_item(catalog, source_key)
            refs = source_references(source_key, datasources, counts)
            if not refs:
                return {"rows": [], "total": 0, "page": page, "page_size": _RECORD_PAGE_SIZE}
            if len(refs) != 1:
                raise HTTPException(400, "record preview is available per generated asset")
            total, rows = reader.source_records_page(
                *refs[0], limit=_RECORD_PAGE_SIZE, offset=(page - 1) * _RECORD_PAGE_SIZE,
            )
            return {"rows": rows, "total": total, "page": page, "page_size": _RECORD_PAGE_SIZE}
        finally:
            store.close()

    @router.get("/sources/{source_key:path}/preview")
    def source_preview(source_key: str, workspace_id: int = 1) -> dict:
        """Return a preview payload for a top-level source row."""
        store = _store(workspace_id)
        try:
            source_system, source_dataset = _parse_generic_source_key(source_key)
            rows = store.list_source_payloads(source_system, source_dataset, limit=None)
            return {
                "source_key": source_key,
                "name": f"{source_system}.{source_dataset}",
                "rows": rows,
            }
        finally:
            store.close()

    @router.get("/sources/{source_key}/download")
    def download_source(source_key: str, workspace_id: int = 1) -> Response:
        """Download a persisted XML parent source."""
        store = _store(workspace_id)
        try:
            if _is_generic_source_key(source_key):
                source_system, source_dataset = _parse_generic_source_key(source_key)
                payload_rows = store.list_source_payloads(source_system, source_dataset, limit=None)
                if not payload_rows:
                    raise HTTPException(404, "download unavailable")
                content = _csv_response_bytes(payload_rows)
                headers = {
                    "Content-Disposition": f'attachment; filename="{source_dataset}.csv"',
                }
                return Response(content=content, media_type="text/csv", headers=headers)
            datasources = _datasource_store().list(workspace_id)
            counts = Counter(_metric_reader(store, workspace_id).source_record_counts())
            datasource = _resolve_download_row(source_key, workspace_id, datasources, counts)
            download_fn = xlsx_download_payload if source_key.startswith("xlsx:") else xml_download_payload
            payload = download_fn(
                datasource,
                counts=counts,
            )
            if payload is None:
                raise HTTPException(404, "download unavailable")
            content, filename, content_type = payload
            headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
            return Response(content=content, media_type=content_type, headers=headers)
        finally:
            store.close()

    @router.delete("/sources/{source_key}")
    def delete_source(source_key: str, workspace_id: int = 1) -> dict:
        """Soft-delete an XML or Excel workbook source from the catalog view."""
        store = _datasource_store()
        if _is_generic_source_key(source_key):
            source_system, source_dataset = _parse_generic_source_key(source_key)
            upsert_generic_source_entry(
                store,
                workspace_id=workspace_id,
                source_system=source_system,
                source_dataset=source_dataset,
            )
            return {"status": "deleted", "source_key": source_key}
        datasource = _resolve_mutable_xml_row(source_key, workspace_id, store)
        mark_deleted_fn = mark_xlsx_source_deleted if source_key.startswith("xlsx:") else mark_xml_source_deleted
        config = mark_deleted_fn(datasource)
        store.update(
            int(datasource["id"]),
            name=datasource["name"],
            kind=datasource["kind"],
            config=config,
            secret=None,
        )
        return {"status": "deleted", "source_key": source_key}

    @router.get("/sources/{source_key:path}/assets/{asset_key}/download")
    def download_asset(source_key: str, asset_key: str, workspace_id: int = 1) -> Response:
        """Download one generated CSV asset for an XML or Excel workbook source."""
        store = _store(workspace_id)
        try:
            datasources = _datasource_store().list(workspace_id)
            counts = Counter(_metric_reader(store, workspace_id).source_record_counts())
            datasource = _resolve_download_row(source_key, workspace_id, datasources, counts)
            detail = build_source_detail_from_counts(source_key, datasources, counts)
            if detail is None:
                raise HTTPException(404, "source not found")
            dataset_payloads = _dataset_payloads(
                store,
                [asset["dataset"] for asset in detail["assets"] if asset.get("dataset")],
                limit=None,
            )
            download_fn = xlsx_download_payload if source_key.startswith("xlsx:") else xml_download_payload
            payload = download_fn(
                datasource,
                asset_key=asset_key,
                payload_rows_by_dataset=dataset_payloads,
                counts=counts,
            )
            if payload is None:
                raise HTTPException(404, "asset download unavailable")
            content, filename, content_type = payload
            headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
            return Response(content=content, media_type=content_type, headers=headers)
        finally:
            store.close()

    @router.delete("/sources/{source_key:path}/assets/{asset_key}")
    def delete_asset(source_key: str, asset_key: str, workspace_id: int = 1) -> dict:
        """Soft-delete one generated asset from the XML or Excel workbook catalog view."""
        store = _datasource_store()
        datasource = _resolve_mutable_xml_row(source_key, workspace_id, store)
        mark_asset_deleted_fn = mark_xlsx_asset_deleted if source_key.startswith("xlsx:") else mark_xml_asset_deleted
        config = mark_asset_deleted_fn(datasource, asset_key)
        store.update(
            int(datasource["id"]),
            name=datasource["name"],
            kind=datasource["kind"],
            config=config,
            secret=None,
        )
        return {"status": "deleted", "source_key": source_key, "asset_key": asset_key}

    @router.get("/sources/{source_key:path}/download", include_in_schema=False)
    def download_source_with_path(source_key: str, workspace_id: int = 1) -> Response:
        """Support downloads for generic source keys containing encoded slashes."""
        return download_source(source_key, workspace_id)

    @router.delete("/sources/{source_key:path}", include_in_schema=False)
    def delete_source_with_path(source_key: str, workspace_id: int = 1) -> dict:
        """Support deletes for generic source keys containing encoded slashes."""
        return delete_source(source_key, workspace_id)

    @router.get("/sources/{source_key:path}", include_in_schema=False)
    def source_detail_with_path(source_key: str, workspace_id: int = 1) -> dict:
        """Support universal details for source keys containing encoded slashes."""
        return source_detail(source_key, workspace_id)

    @router.post("/relate")
    def relate(req: RelateRequest) -> dict:
        """Derive relationships from foreign-key attribute links, then reproject.

        Each link creates edges where source_type.source_attr ==
        target_type.target_attr (exact, no LLM). Idempotent with replace=True.
        """
        from aryx.pipeline.fk_edges import link_by_attribute

        store = _store(req.workspace_id)
        try:
            cleared = store.clear_relationships() if req.replace else 0
            created = 0
            per_link = []
            for link in req.links:
                n = link_by_attribute(store, link.source_type, link.source_attr,
                                      link.target_type, link.target_attr, link.name)
                per_link.append({"name": link.name, "created": n})
                created += n
            projected = _reproject(req.workspace_id, store) if req.reproject else None
            return {"cleared": cleared, "created": created,
                    "per_link": per_link, "projected": projected}
        except Exception as exc:  # noqa: BLE001
            logger.warning("data relate failed: %s", exc)
            return {"error": f"relate failed: {exc}"}

    return router


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

    def workspace_summary(self) -> dict:
        return explore.summarize(  # type: ignore[attr-defined]
            self._store.list_entities(), self._store.list_members_provenance(),
        )

    def source_records_page(
        self, system: str, dataset: str, *, limit: int, offset: int,
    ) -> tuple[int, list[dict]]:
        rows = self._store.list_source_payloads(system, dataset, limit=None)  # type: ignore[attr-defined]
        return len(rows), rows[offset:offset + limit]


def _metric_reader(store: EntityStore, workspace_id: int) -> SourceMetricsStore | _LegacyMetricReader:
    """Use database aggregates in production and compatibility shaping in unit fakes."""
    if isinstance(store, EntityStore):
        return _metrics_store(workspace_id)
    return _LegacyMetricReader(store)


def _catalog_snapshot(
    store: EntityStore, workspace_id: int,
) -> tuple[SourceMetricsStore | _LegacyMetricReader, list[dict], Counter, list[dict]]:
    """Load bounded catalog inputs and preserve generic-source revival behavior."""
    reader = _metric_reader(store, workspace_id)
    counts = Counter(reader.source_record_counts())
    datasource_store = _datasource_store()
    datasources = datasource_store.list(workspace_id)
    if _revive_generic_sources_from_recent_jobs(
        datasource_store, workspace_id, datasources, store.list_source_activity(),
    ):
        datasources = datasource_store.list(workspace_id)
    catalog = build_source_catalog_from_counts(datasources, counts)
    return reader, datasources, counts, catalog


def _catalog_item(catalog: list[dict], source_key: str) -> dict:
    item = next((row for row in catalog if row.get("source_key") == source_key), None)
    if item is None:
        raise HTTPException(404, "source not found")
    return item


def _universal_source_detail(
    store: EntityStore,
    item: dict,
    datasources: list[dict],
    counts: Counter,
    stats: list[tuple[str, int]],
) -> dict:
    source_key = str(item["source_key"])
    grouped = _build_source_detail_payload(store, datasources, source_key, counts)
    detail = grouped or {
        "source_key": source_key,
        "name": item["name"],
        "status": "Ready" if item.get("ready") else "Configured",
        "generatedAssetCount": 0,
        "record_count": item.get("record_count", 0),
        "primary": {"label": item.get("display_kind"), "status": "Active",
                    "actions": item.get("actions", {})},
        "assets": [],
    }
    total_entities = sum(count for _name, count in stats)
    detail.update({
        "display_kind": item.get("display_kind"),
        "kind": item.get("kind"),
        "ready": bool(item.get("ready")),
        "actions": item.get("actions", {}),
        "isXmlParent": bool(item.get("isXmlParent")),
        "detail_kind": "grouped_assets" if item.get("isXmlParent")
                       else "preview" if not source_key.startswith("ds:") else "configured",
        "entity_summary": {
            "total_entities": total_entities,
            "type_count": len(stats),
            "types": [{"name": name, "count": count} for name, count in stats[:12]],
        },
    })
    return detail


def _find_datasource_by_prefix(source_key: str, workspace_id: int, prefix: str) -> dict:
    if not source_key.startswith(prefix):
        raise HTTPException(404, "source not found")
    try:
        datasource_id = int(source_key.split(":", 1)[1])
    except ValueError as exc:
        raise HTTPException(404, "source not found") from exc
    datasource = _datasource_store().get(datasource_id)
    if not datasource or int(datasource.get("workspace_id", 0)) != int(workspace_id):
        raise HTTPException(404, "source not found")
    return datasource


def _find_xml_datasource(source_key: str, workspace_id: int) -> dict:
    return _find_datasource_by_prefix(source_key, workspace_id, "xml:")


def _find_xlsx_datasource(source_key: str, workspace_id: int) -> dict:
    return _find_datasource_by_prefix(source_key, workspace_id, "xlsx:")


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


def _dataset_payloads(
    store: EntityStore,
    datasets: list[str],
    *,
    limit: int | None,
) -> dict[str, list[dict]]:
    payloads: dict[str, list[dict]] = {}
    for dataset in datasets:
        if dataset in payloads:
            continue
        payloads[dataset] = store.list_source_payloads("csv", dataset, limit=limit)
    return payloads


def _csv_response_bytes(payload_rows: list[dict]) -> bytes:
    import csv
    import io

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


_DETAIL_FILENAME_RE = re.compile(r"([A-Za-z0-9_. -]+\.(?:csv|json))", re.IGNORECASE)


def _parse_job_time(value: object) -> datetime | None:
    if isinstance(value, _DATETIME_TYPE):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _recent_ingested_generic_keys(workspace_id: int) -> set[tuple[str, str]]:
    jobs = _job_store()
    try:
        rows = jobs.list_recent(workspace_id)
    finally:
        jobs.close()
    cutoff = datetime.now(UTC) - timedelta(hours=2)
    keys: set[tuple[str, str]] = set()
    for row in rows:
        if row.get("status") != "complete":
            continue
        finished_at = _parse_job_time(row.get("finished_at")) or _parse_job_time(row.get("updated_at"))
        if finished_at is None or finished_at < cutoff:
            continue
        detail = str(row.get("detail") or "")
        if detail.lower().startswith("processing "):
            detail = detail[len("Processing "):]
        for match in _DETAIL_FILENAME_RE.findall(detail):
            stem, suffix = match.rsplit(".", 1)
            keys.add((suffix.lower(), stem))
    return keys


def _hidden_generic_baseline(row: dict, meta: dict) -> datetime | None:
    deleted_at = _parse_job_time(meta.get("deleted_at"))
    if deleted_at is not None:
        return deleted_at
    return _parse_job_time(row.get("created_at"))


def _revive_generic_sources_from_recent_jobs(
    datasource_store: DatasourceStore,
    workspace_id: int,
    datasources: list[dict],
    source_activity: dict[tuple[str, str], object],
) -> bool:
    hidden_rows: list[tuple[dict, dict]] = []
    for row in datasources:
        meta = (row.get("config") or {}).get("source_catalog", {}).get("generic")
        if isinstance(meta, dict) and meta.get("deleted"):
            hidden_rows.append((row, meta))
    if not hidden_rows:
        return False

    recent_keys = _recent_ingested_generic_keys(workspace_id)
    revived = False
    for row, meta in hidden_rows:
        key = (
            str(meta.get("source_system") or ""),
            str(meta.get("source_dataset") or ""),
        )
        latest_activity = _parse_job_time(source_activity.get(key))
        baseline = _hidden_generic_baseline(row, meta)
        has_new_landed_data = (
            latest_activity is not None
            and baseline is not None
            and latest_activity > baseline
        )
        if not has_new_landed_data and key not in recent_keys:
            continue
        datasource_store.update(
            int(row["id"]),
            name=row.get("name") or f"{key[0]}.{key[1]}",
            kind=row.get("kind") or "source_catalog",
            config={
                "source_catalog": {
                    "generic": {
                        "source_system": key[0],
                        "source_dataset": key[1],
                        "is_active": True,
                        "deleted": False,
                        "deleted_at": None,
                    },
                },
            },
            secret=None,
        )
        revived = True
    return revived


def _build_source_detail_payload(
    store: EntityStore,
    datasources: list[dict],
    source_key: str,
    counts: Counter[tuple[str, str]],
) -> dict | None:
    detail = build_source_detail_from_counts(source_key, datasources, counts)
    if detail is None:
        return None
    dataset_payloads = _dataset_payloads(
        store,
        [asset["dataset"] for asset in detail["assets"] if asset.get("dataset")],
        limit=5,
    )
    return build_source_detail_from_counts(
        source_key,
        datasources,
        counts,
        dataset_payloads=dataset_payloads,
    )


def _resolve_download_row(
    source_key: str,
    workspace_id: int,
    datasources: list[dict],
    counts: Counter[tuple[str, str]],
) -> dict:
    if source_key.startswith("xml:"):
        return _find_xml_datasource(source_key, workspace_id)
    if source_key.startswith("xlsx:"):
        # No legacy fallback for xlsx — every workbook upload always creates
        # a real datasource_store row via upsert_xlsx_catalog_entry, unlike
        # XML's pre-catalog era rows that need on-the-fly reconstruction.
        return _find_xlsx_datasource(source_key, workspace_id)
    if not source_key.startswith("legacy-xml:"):
        raise HTTPException(404, "source not found")
    prefix = source_key.split(":", 1)[1]
    existing = find_legacy_xml_row(datasources, prefix)
    if existing is not None and (existing.get("config") or {}).get("source_catalog", {}).get("xml", {}).get("generated_assets"):
        return existing
    detail = build_source_detail_from_counts(source_key, datasources, counts)
    if detail is None:
        raise HTTPException(404, "source not found")
    datasets = [asset["dataset"] for asset in detail["assets"] if asset.get("dataset")]
    return legacy_xml_row(prefix, datasets, workspace_id=workspace_id)


def _resolve_mutable_xml_row(
    source_key: str,
    workspace_id: int,
    store: DatasourceStore,
) -> dict:
    if source_key.startswith("xml:"):
        return _find_xml_datasource(source_key, workspace_id)
    if source_key.startswith("xlsx:"):
        return _find_xlsx_datasource(source_key, workspace_id)
    if not source_key.startswith("legacy-xml:"):
        raise HTTPException(404, "source not found")
    entity_store = _store(workspace_id)
    try:
        datasources = store.list(workspace_id)
        counts = Counter(_metric_reader(entity_store, workspace_id).source_record_counts())
        prefix = source_key.split(":", 1)[1]
        existing = find_legacy_xml_row(datasources, prefix)
        if existing is not None and (existing.get("config") or {}).get("source_catalog", {}).get("xml", {}).get("generated_assets"):
            return existing
        detail = build_source_detail_from_counts(source_key, datasources, counts)
        if detail is None:
            raise HTTPException(404, "source not found")
        datasets = [asset["dataset"] for asset in detail["assets"] if asset.get("dataset")]
        return upsert_legacy_xml_catalog_entry(
            store,
            workspace_id=workspace_id,
            prefix=prefix,
            datasets=datasets,
        )
    finally:
        entity_store.close()


def _reproject(workspace_id: int, store: EntityStore) -> dict:
    """Rebuild the FalkorDB projection so the graph reflects new edges."""
    from aryx.graph.falkor_store import FalkorStore
    from aryx.naming import ws_graph
    from aryx.project import project_graph

    falkor = FalkorStore(get_settings().graph_url, ws_graph(workspace_id))
    return project_graph(store, falkor, workspace_id=workspace_id)
