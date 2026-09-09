"""REST API ingest — fetch records from any JSON endpoint and pipeline to graph.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`rest_ingest_models.py` (`RestPreviewRequest`/`RestIngestRequest`) and
`rest_ingest_job.py` (`_type_from_url`/`_run_rest`), both re-imported
here. Zero whitebox test patches exist anywhere against
`aryx.api.rest_ingest_api.*` (confirmed via grep), so the split was
purely mechanical. `rest_ingest_router` — wiring the routes to the
background job — stays here.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from aryx.api.rest_ingest_job import _run_rest, _type_from_url
from aryx.api.rest_ingest_models import RestIngestRequest, RestPreviewRequest
from aryx.config import get_settings
from aryx.connectors.rest_api import RestApiConnector
from aryx.store.job_store import JobStore

logger = logging.getLogger(__name__)

__all__ = ["RestIngestRequest", "RestPreviewRequest", "rest_ingest_router"]


def rest_ingest_router() -> APIRouter:
    router = APIRouter(prefix="/ingest/rest")

    @router.post("/preview")
    def preview(req: RestPreviewRequest) -> dict[str, Any]:
        """Fetch the URL and return the first 10 records + inferred type."""
        try:
            conn = RestApiConnector(
                url=req.url, headers=req.headers,
                record_path=req.record_path,
                page_param=req.page_param,
                next_page_path=req.next_page_path,
                max_pages=1,
            )
            recs = list(conn.extract())
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"REST fetch failed: {exc}") from exc
        inferred_type = _type_from_url(req.url)
        first_keys = list(recs[0].payload.keys()) if recs else []
        suggested_key = next((k for k in ("id", "uuid", "key") if k in first_keys),
                             first_keys[0] if first_keys else "id")
        return {
            "count": len(recs),
            "sample": [r.payload for r in recs[:10]],
            "inferred_type": inferred_type,
            "suggested_match_key": suggested_key,
        }

    @router.post("/ingest")
    def ingest(req: RestIngestRequest,
               background_tasks: BackgroundTasks) -> dict[str, Any]:
        """Fetch all pages and run the full entity pipeline to the graph."""
        if not req.url.strip():
            raise HTTPException(400, "url is required")
        otype = req.ontology_type.strip() or _type_from_url(req.url)
        keys = req.match_keys or ["id"]
        settings = get_settings()
        job_id = uuid.uuid4().hex
        jobs = JobStore(settings.effective_dsn())
        try:
            jobs.create(job_id, "rest", req.url, req.workspace_id)
        finally:
            jobs.close()
        background_tasks.add_task(
            _run_rest, req.url, req.headers, req.record_path,
            req.page_param, req.next_page_path, req.max_pages,
            otype, keys, job_id, req.workspace_id,
        )
        return {"status": "queued", "job_id": job_id,
                "ontology_type": otype, "match_keys": keys}

    return router
