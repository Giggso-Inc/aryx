"""Admin API: ingestion triggers with durable per-stage job progress."""
from __future__ import annotations

import logging
import uuid
from typing import Any

import os

import psycopg
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from aryx import llm_runtime
from aryx.broker import Broker, ModelSpec, Registry, TokenGovernor
from aryx.config import get_settings
from aryx.connectors.postgres import PostgresConnector
from aryx.graph import FalkorStore
from aryx.pipeline.enrich import _build_type_ancestors
from aryx.pipeline.orchestrate import run_pipeline
from aryx.project import project_graph
from aryx.store.entity_store import EntityStore
from aryx.store.job_store import JobStore
from aryx.store.migrate import apply_migrations
from aryx.store.ontology_store import OntologyStore
from aryx.workspaces import ws_graph
from aryx.api.security import require_api_key, write_api_key


def _local_broker() -> Broker:
    """Pipeline broker — honours Settings → LLM Provider (live, no restart).

    Reads aryx.llm_runtime.status() so the doc ingest pipeline + the Ask API
    share ONE config. Switching provider/model in the Settings panel now
    drives both. `embed_config` below is always Ollama-shaped (model +
    endpoint) — harmless when ARYX_EMBED_BACKEND is "oci" or "gemini",
    since Broker.embed() checks that global setting BEFORE ever touching
    this dict, routing to _oci_embed/_gemini_embed instead (see
    docs/LLM_GEMINI_MIGRATION_PLAN.md). Only actually used on the default
    "local" (Ollama) backend.
    """
    cfg = llm_runtime.status()
    provider = str(cfg.get("provider") or "ollama")
    endpoint = str(cfg.get("endpoint") or "http://ollama:11434")
    menial = str(cfg.get("menial_model") or "qwen3.5:0.8b")
    answer = str(cfg.get("answer_model") or "lfm2.5-thinking:latest")
    is_ollama = provider == "ollama"
    api_key_ref = None if is_ollama else llm_runtime._KEY_REF
    embed_model = os.environ.get("ARYX_EMBED_MODEL", "nomic-embed-text")
    embed_endpoint = os.environ.get(
        "ARYX_EMBED_ENDPOINT",
        endpoint if is_ollama else "http://ollama:11434",
    )
    registry = Registry()
    for name, tier in ((menial, "cheap"), (answer, "frontier")):
        registry.add(ModelSpec(name=name, provider=provider, tier=tier,
                               local=is_ollama, endpoint=endpoint,
                               api_key_ref=api_key_ref))
    return Broker(
        registry, TokenGovernor({}),
        secrets=llm_runtime._RuntimeSecrets(),
        embed_config={"model": embed_model, "endpoint": embed_endpoint},
    )

logger = logging.getLogger(__name__)


class EntityCreateRequest(BaseModel):
    ontology_type: str
    attributes: dict[str, Any] = {}
    workspace_id: int = 1


class EntityUpdateRequest(BaseModel):
    attributes: dict[str, Any]


class FkLink(BaseModel):
    source_type: str
    source_attr: str
    target_type: str
    target_attr: str
    name: str


class IngestDbRequest(BaseModel):
    table: str
    ontology_type: str
    match_keys: str
    system: str = "postgresql"
    key_column: str = "id"
    fk_links: list[FkLink] = []
    workspace_id: int = 1


def _run_db(req: IngestDbRequest, job_id: str) -> None:
    settings = get_settings()
    jobs = JobStore(settings.rdb_dsn)
    try:
        connector = PostgresConnector(
            dsn=settings.rdb_dsn, table=req.table,
            key_column=req.key_column, batch_size=settings.batch_size,
        )
        summary = run_pipeline(
            connector=connector, dsn=settings.rdb_dsn,
            system=req.system, dataset=req.table,
            ontology_type=req.ontology_type,
            match_keys=[k.strip() for k in req.match_keys.split(",") if k.strip()],
            graph_url=settings.graph_url, broker=_local_broker(),
            on_progress=lambda stage, pct, detail: jobs.update_stage(job_id, stage, pct, detail),
            fk_links=[link.model_dump() for link in req.fk_links],
            workspace_id=req.workspace_id,
            relate=True,
        )
        jobs.finish(job_id, run_id=summary.get("run_id"), status="complete")
    except Exception as exc:  # noqa: BLE001 — record failure for the dashboard
        logger.warning("ingest failed job=%s: %s", job_id, exc)
        jobs.finish(job_id, run_id=None, status="failed", error=str(exc))
    finally:
        jobs.close()


def admin_router() -> APIRouter:
    router = APIRouter(prefix="/admin")

    @router.get("/entities/{entity_id}")
    def get_entity(entity_id: int, workspace_id: int = 1) -> dict[str, Any]:
        """Fetch full entity record (including attributes) from Postgres."""
        settings = get_settings()
        estore = EntityStore(settings.rdb_dsn, workspace_id)
        try:
            row = estore.get_entity(entity_id)
        finally:
            estore.close()
        if row is None:
            raise HTTPException(404, f"entity {entity_id} not found")
        return {"id": row[0], "ontology_type": row[1], "attributes": row[2]}

    @router.post("/entities")
    def create_entity(req: EntityCreateRequest,
                      _: str | None = Depends(write_api_key)) -> dict[str, Any]:
        """Create a new entity in Postgres and project it into FalkorDB."""
        settings = get_settings()
        estore = EntityStore(settings.rdb_dsn, req.workspace_id)
        try:
            entity_id = estore.create_entity(req.ontology_type, req.attributes)
        finally:
            estore.close()
        type_ancestors = _build_type_ancestors(settings.rdb_dsn, req.workspace_id)
        labels = type_ancestors.get(req.ontology_type, [])
        FalkorStore(settings.graph_url, ws_graph(req.workspace_id)).add_entity(
            entity_id, req.ontology_type, req.attributes, labels=labels,
        )
        return {"status": "ok", "entity_id": entity_id,
                "ontology_type": req.ontology_type, "workspace_id": req.workspace_id}

    @router.put("/entities/{entity_id}")
    def update_entity(entity_id: int, req: EntityUpdateRequest,
                      workspace_id: int = 1,
                      _: str | None = Depends(write_api_key)) -> dict[str, Any]:
        """Replace an entity's attributes in Postgres and resync the FalkorDB node."""
        settings = get_settings()
        estore = EntityStore(settings.rdb_dsn, workspace_id)
        try:
            result = estore.update_entity(entity_id, req.attributes)
        finally:
            estore.close()
        if result is None:
            raise HTTPException(404, f"entity {entity_id} not found in workspace {workspace_id}")
        ontology_type, attrs = result
        type_ancestors = _build_type_ancestors(settings.rdb_dsn, workspace_id)
        labels = type_ancestors.get(ontology_type, [])
        FalkorStore(settings.graph_url, ws_graph(workspace_id)).add_entity(
            entity_id, ontology_type, attrs, labels=labels,
        )
        return {"status": "ok", "entity_id": entity_id, "ontology_type": ontology_type}

    @router.delete("/entities/{entity_id}")
    def delete_entity(entity_id: int, workspace_id: int = 1,
                      _: str | None = Depends(write_api_key)) -> dict[str, Any]:
        """Delete an entity from Postgres and remove the node from FalkorDB."""
        settings = get_settings()
        estore = EntityStore(settings.rdb_dsn, workspace_id)
        try:
            found = estore.delete_entity(entity_id)
        finally:
            estore.close()
        if not found:
            raise HTTPException(404, f"entity {entity_id} not found in workspace {workspace_id}")
        FalkorStore(settings.graph_url, ws_graph(workspace_id)).remove_entity(entity_id)
        return {"status": "ok", "entity_id": entity_id, "deleted": True}

    @router.post("/ingest/db")
    def ingest_db(req: IngestDbRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
        settings = get_settings()
        jobs = JobStore(settings.rdb_dsn)
        job_id = uuid.uuid4().hex
        try:
            jobs.archive_old(30)
            jobs.create(job_id, req.system, req.table, req.workspace_id)
        finally:
            jobs.close()
        background_tasks.add_task(_run_db, req, job_id)
        return {"status": "queued", "job_id": job_id, "table": req.table}

    @router.post("/graph/rebuild")
    def rebuild_graph(workspace_id: int = 1, _: str = Depends(require_api_key)) -> dict[str, Any]:
        """Rebuild the FalkorDB projection from Postgres (source of truth).

        Safe to call at any time — it overwrites the graph with the current
        Postgres state. Use after a container restart kills an in-flight
        project stage, or to resync after manual DB edits.
        """
        settings = get_settings()
        estore = EntityStore(settings.rdb_dsn, workspace_id)
        try:
            type_ancestors = _build_type_ancestors(settings.rdb_dsn, workspace_id)
            counts = project_graph(
                estore,
                FalkorStore(settings.graph_url, ws_graph(workspace_id)),
                type_ancestors=type_ancestors,
                workspace_id=workspace_id,
            )
        finally:
            estore.close()
        logger.info("manual graph rebuild workspace=%s counts=%s", workspace_id, counts)
        return {"status": "ok", "workspace_id": workspace_id, **counts}

    @router.get("/runs")
    def list_runs() -> list[dict[str, Any]]:
        settings = get_settings()
        with psycopg.connect(settings.rdb_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT run_id, source_system, source_dataset, status, "
                    "record_count, started_at, finished_at "
                    "FROM aryx_run ORDER BY run_id DESC LIMIT 50"
                )
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]

    return router
