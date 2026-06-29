"""REST API ingest — fetch records from any JSON endpoint and pipeline to graph."""
from __future__ import annotations

import ipaddress
import logging
import re
import uuid
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, field_validator

from aryx.api.admin_api import _local_broker
from aryx.config import get_settings
from aryx.connectors.rest_api import RestApiConnector
from aryx.pipeline.orchestrate import run_pipeline
from aryx.store.job_store import JobStore
from aryx.store.migrate import apply_migrations

logger = logging.getLogger(__name__)

# Hop-by-hop and host-override headers that must never be forwarded to
# third-party endpoints — prevents header injection attacks.
_BLOCKED_HEADERS = frozenset({
    "host", "connection", "transfer-encoding", "upgrade",
    "proxy-authorization", "proxy-authenticate", "te", "trailers",
})

# RFC-1918, loopback, and cloud IMDS ranges blocked to prevent SSRF.
_BLOCKED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0",
                             "metadata.google.internal"})
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / IMDS
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _check_url(v: str) -> str:
    parsed = urlparse(v)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("url must use http or https")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("url must include a hostname")
    if host in _BLOCKED_HOSTS:
        raise ValueError(f"url targets a blocked host: {host}")
    try:
        addr = ipaddress.ip_address(host)
        if any(addr in net for net in _PRIVATE_NETS):
            raise ValueError(f"url targets a private or reserved address: {host}")
    except ValueError as exc:
        if "url targets" in str(exc):
            raise
        # Not an IP literal — hostname allowed; DNS resolved at request time
    return v


def _check_headers(v: dict[str, str]) -> dict[str, str]:
    bad = {k for k in v if k.lower() in _BLOCKED_HEADERS}
    if bad:
        raise ValueError(f"headers may not include: {sorted(bad)}")
    return v


class RestPreviewRequest(BaseModel):
    workspace_id: int = 1
    url: str
    headers: dict[str, str] = {}
    record_path: str = ""
    page_param: str = ""
    next_page_path: str = ""
    context: str = ""

    @field_validator("url")
    @classmethod
    def _no_ssrf(cls, v: str) -> str:
        return _check_url(v)

    @field_validator("headers")
    @classmethod
    def _safe_headers(cls, v: dict[str, str]) -> dict[str, str]:
        return _check_headers(v)


class RestIngestRequest(BaseModel):
    workspace_id: int = 1
    url: str
    headers: dict[str, str] = {}
    record_path: str = ""
    page_param: str = ""
    next_page_path: str = ""
    max_pages: int = Field(default=20, ge=1, le=500)
    ontology_type: str = ""
    match_keys: list[str] = ["id"]
    context: str = ""

    @field_validator("url")
    @classmethod
    def _no_ssrf(cls, v: str) -> str:
        return _check_url(v)

    @field_validator("headers")
    @classmethod
    def _safe_headers(cls, v: dict[str, str]) -> dict[str, str]:
        return _check_headers(v)


def _type_from_url(url: str) -> str:
    """Derive a PascalCase entity type from the last non-empty URL path segment.

    https://api.example.com/v1/customers  ->  Customer
    https://api.example.com/v1/support-tickets  ->  SupportTicket
    """
    path = url.split("?")[0].rstrip("/")
    segment = path.split("/")[-1] if "/" in path else path
    segment = re.sub(r"[^a-zA-Z0-9 ]", " ", segment).strip()
    words = [w for w in segment.replace("-", " ").replace("_", " ").split() if w]
    if not words:
        return "Entity"
    def _singular(w: str) -> str:
        if w.endswith("ies"):
            return w[:-3] + "y"
        if len(w) > 2 and w.endswith("s") and not w.endswith("ss"):
            return w[:-1]
        return w
    return "".join(_singular(w).title() for w in words)


def _run_rest(url: str, headers: dict, record_path: str, page_param: str,
              next_page_path: str, max_pages: int, ontology_type: str,
              match_keys: list[str], job_id: str, workspace_id: int) -> None:
    settings = get_settings()
    jobs = None
    try:
        jobs = JobStore(settings.rdb_dsn)
        jobs.update_stage(job_id, "Fetch", 10, f"Fetching from {url}")
        connector = RestApiConnector(
            url=url, headers=headers, record_path=record_path,
            page_param=page_param, next_page_path=next_page_path,
            max_pages=max_pages,
        )
        run_pipeline(
            connector=connector, dsn=settings.rdb_dsn,
            system="rest", dataset=url,
            ontology_type=ontology_type, match_keys=match_keys,
            graph_url=settings.graph_url, broker=_local_broker(),
            on_progress=lambda s, p, d: jobs.update_stage(job_id, s, p, d),
            workspace_id=workspace_id,
            relate=True,
        )
        jobs.finish(job_id, run_id=None, status="complete")
    except Exception as exc:  # noqa: BLE001
        logger.warning("rest ingest failed job=%s: %s", job_id, exc)
        if jobs is not None:
            jobs.finish(job_id, run_id=None, status="failed", error=str(exc))
    finally:
        if jobs is not None:
            jobs.close()


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
        apply_migrations(settings.rdb_dsn)
        job_id = uuid.uuid4().hex
        jobs = JobStore(settings.rdb_dsn)
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
