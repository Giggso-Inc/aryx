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

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from aryx import explore
from aryx.config import get_settings
from aryx.source_catalog import (
    build_source_catalog,
    build_source_detail,
    find_legacy_xml_row,
    legacy_xml_row,
    mark_xml_asset_deleted,
    mark_xml_source_deleted,
    upsert_generic_source_entry,
    upsert_legacy_xml_catalog_entry,
    xml_download_payload,
)
from aryx.store.entity_store import EntityStore
from aryx.store.datasource_store import DatasourceStore
from aryx.store.job_store import JobStore

logger = logging.getLogger(__name__)


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


def data_router() -> APIRouter:
    router = APIRouter(prefix="/data")

    @router.get("/summary")
    def summary(workspace_id: int = 1) -> dict:
        """Type counts, source breakdown, and the dedup story."""
        store = _store(workspace_id)
        try:
            return explore.summarize(store.list_entities(),
                                     store.list_members_provenance())
        except Exception as exc:  # noqa: BLE001 — surface to the Data UI
            logger.warning("data summary failed: %s", exc)
            return {"error": f"data unavailable: {exc}"}

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
        """Return the XML-aware source catalog rendered by the Data tab."""
        store = _store(workspace_id)
        try:
            datasource_store = _datasource_store()
            datasources = datasource_store.list(workspace_id)
            source_activity = store.list_source_activity()
            if _revive_generic_sources_from_recent_jobs(
                datasource_store,
                workspace_id,
                datasources,
                source_activity,
            ):
                datasources = datasource_store.list(workspace_id)
            return build_source_catalog(datasources, store.list_members_provenance())
        except Exception as exc:  # noqa: BLE001
            logger.warning("data sources failed: %s", exc)
            return []
        finally:
            store.close()

    @router.get("/sources/{source_key}")
    def source_detail(source_key: str, workspace_id: int = 1) -> dict:
        """Return the in-tab XML detail payload for a source key."""
        store = _store(workspace_id)
        try:
            datasources = _datasource_store().list(workspace_id)
            detail = _build_source_detail_payload(store, datasources, source_key)
            if detail is None:
                raise HTTPException(404, "source not found")
            return detail
        finally:
            store.close()

    @router.get("/sources/{source_key}/preview")
    def source_preview(source_key: str, workspace_id: int = 1) -> dict:
        """Return a preview payload for a top-level source row."""
        store = _store(workspace_id)
        try:
            source_system, source_dataset = _parse_generic_source_key(source_key)
            rows = store.list_source_payloads(source_system, source_dataset, limit=5)
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
            provenance = list(store.list_members_provenance())
            datasource = _resolve_download_row(source_key, workspace_id, datasources, provenance)
            payload = xml_download_payload(
                datasource,
                counts=_provenance_counts(provenance),
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
        """Soft-delete an XML source from the catalog view."""
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
        config = mark_xml_source_deleted(datasource)
        store.update(
            int(datasource["id"]),
            name=datasource["name"],
            kind=datasource["kind"],
            config=config,
            secret=None,
        )
        return {"status": "deleted", "source_key": source_key}

    @router.get("/sources/{source_key}/assets/{asset_key}/download")
    def download_asset(source_key: str, asset_key: str, workspace_id: int = 1) -> Response:
        """Download one generated CSV asset for an XML source."""
        store = _store(workspace_id)
        try:
            datasources = _datasource_store().list(workspace_id)
            provenance = list(store.list_members_provenance())
            datasource = _resolve_download_row(source_key, workspace_id, datasources, provenance)
            detail = build_source_detail(source_key, datasources, provenance)
            if detail is None:
                raise HTTPException(404, "source not found")
            dataset_payloads = _dataset_payloads(
                store,
                [asset["dataset"] for asset in detail["assets"] if asset.get("dataset")],
                limit=None,
            )
            payload = xml_download_payload(
                datasource,
                asset_key=asset_key,
                payload_rows_by_dataset=dataset_payloads,
                counts=_provenance_counts(provenance),
            )
            if payload is None:
                raise HTTPException(404, "asset download unavailable")
            content, filename, content_type = payload
            headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
            return Response(content=content, media_type=content_type, headers=headers)
        finally:
            store.close()

    @router.delete("/sources/{source_key}/assets/{asset_key}")
    def delete_asset(source_key: str, asset_key: str, workspace_id: int = 1) -> dict:
        """Soft-delete one generated asset from the XML catalog view."""
        store = _datasource_store()
        datasource = _resolve_mutable_xml_row(source_key, workspace_id, store)
        config = mark_xml_asset_deleted(datasource, asset_key)
        store.update(
            int(datasource["id"]),
            name=datasource["name"],
            kind=datasource["kind"],
            config=config,
            secret=None,
        )
        return {"status": "deleted", "source_key": source_key, "asset_key": asset_key}

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


def _find_xml_datasource(source_key: str, workspace_id: int) -> dict:
    if not source_key.startswith("xml:"):
        raise HTTPException(404, "source not found")
    try:
        datasource_id = int(source_key.split(":", 1)[1])
    except ValueError as exc:
        raise HTTPException(404, "source not found") from exc
    datasource = _datasource_store().get(datasource_id)
    if not datasource or int(datasource.get("workspace_id", 0)) != int(workspace_id):
        raise HTTPException(404, "source not found")
    return datasource


def _is_generic_source_key(source_key: str) -> bool:
    return ":" in source_key and not source_key.startswith(("xml:", "legacy-xml:", "ds:"))


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
    if isinstance(value, datetime):
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
) -> dict | None:
    provenance = list(store.list_members_provenance())
    detail = build_source_detail(source_key, datasources, provenance)
    if detail is None:
        return None
    dataset_payloads = _dataset_payloads(
        store,
        [asset["dataset"] for asset in detail["assets"] if asset.get("dataset")],
        limit=5,
    )
    return build_source_detail(
        source_key,
        datasources,
        provenance,
        dataset_payloads=dataset_payloads,
    )


def _resolve_download_row(
    source_key: str,
    workspace_id: int,
    datasources: list[dict],
    provenance: list[tuple[int, str, str, str]],
) -> dict:
    if source_key.startswith("xml:"):
        return _find_xml_datasource(source_key, workspace_id)
    if not source_key.startswith("legacy-xml:"):
        raise HTTPException(404, "source not found")
    prefix = source_key.split(":", 1)[1]
    existing = find_legacy_xml_row(datasources, prefix)
    if existing is not None and (existing.get("config") or {}).get("source_catalog", {}).get("xml", {}).get("generated_assets"):
        return existing
    detail = build_source_detail(source_key, datasources, provenance)
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
    if not source_key.startswith("legacy-xml:"):
        raise HTTPException(404, "source not found")
    entity_store = _store(workspace_id)
    try:
        datasources = store.list(workspace_id)
        provenance = list(entity_store.list_members_provenance())
        prefix = source_key.split(":", 1)[1]
        existing = find_legacy_xml_row(datasources, prefix)
        if existing is not None and (existing.get("config") or {}).get("source_catalog", {}).get("xml", {}).get("generated_assets"):
            return existing
        detail = build_source_detail(source_key, datasources, provenance)
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
