"""Admin API: ingestion triggers with durable per-stage job progress.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03),
`_local_broker` moved to `admin_broker.py` and the request models moved
to `admin_models.py` (both zero patch risk, re-imported/re-exported
here). `admin_router()` stays as a deliberate exception: `get_settings`/
`EntityStore`/`FalkorStore`/`_build_type_ancestors`/`project_graph` are
all directly whitebox-patched (`aryx.api.admin_api.*`) by
`tests/test_admin_api.py` and called from its route closures (splitting
FastAPI route closures across files would also be a much larger
architectural change than this plan's mechanical splits).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from aryx.api.admin_broker import _local_broker
from aryx.api.admin_models import EntityCreateRequest, EntityUpdateRequest, FkLink, IngestDbRequest
from aryx.config import get_settings
from aryx.connectors.postgres import PostgresConnector
from aryx.graph import FalkorStore
from aryx.pipeline.enrich.enrich import _build_type_ancestors
from aryx.pipeline.orchestrate import run_pipeline
from aryx.project import project_graph
from aryx.store.entity_store import EntityStore
from aryx.store.job_store import JobStore
from aryx.workspaces import ws_graph
from aryx.api.security import require_api_key, write_api_key
from aryx.api.workspace_scope import resolve_workspace_id_warn

__all__ = [
    "EntityCreateRequest",
    "EntityUpdateRequest",
    "FkLink",
    "IngestDbRequest",
    "_local_broker",
    "admin_router",
]

logger = logging.getLogger(__name__)


def _run_db(req: IngestDbRequest, job_id: str) -> None:
    settings = get_settings()
    jobs = JobStore(settings.effective_dsn())
    try:
        connector = PostgresConnector(
            dsn=settings.effective_dsn(), table=req.table,
            key_column=req.key_column, batch_size=settings.batch_size,
        )
        summary = run_pipeline(
            connector=connector, dsn=settings.effective_dsn(),
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
        estore = EntityStore(settings.effective_dsn(), workspace_id)
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
        estore = EntityStore(settings.effective_dsn(), req.workspace_id)
        try:
            entity_id = estore.create_entity(req.ontology_type, req.attributes)
        finally:
            estore.close()
        type_ancestors = _build_type_ancestors(settings.effective_dsn(), req.workspace_id)
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
        estore = EntityStore(settings.effective_dsn(), workspace_id)
        try:
            result = estore.update_entity(entity_id, req.attributes)
        finally:
            estore.close()
        if result is None:
            raise HTTPException(404, f"entity {entity_id} not found in workspace {workspace_id}")
        ontology_type, attrs = result
        type_ancestors = _build_type_ancestors(settings.effective_dsn(), workspace_id)
        labels = type_ancestors.get(ontology_type, [])
        FalkorStore(settings.graph_url, ws_graph(workspace_id)).add_entity(
            entity_id, ontology_type, attrs, labels=labels,
        )
        return {"status": "ok", "entity_id": entity_id, "ontology_type": ontology_type}

    @router.delete("/entities/{entity_id}")
    def delete_entity(entity_id: int, workspace_id: int | None = None,
                      _: str | None = Depends(write_api_key)) -> dict[str, Any]:
        """Delete an entity from Postgres and remove the node from FalkorDB."""
        workspace_id = resolve_workspace_id_warn(workspace_id, "DELETE /admin/entities/{id}")
        settings = get_settings()
        estore = EntityStore(settings.effective_dsn(), workspace_id)
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
        jobs = JobStore(settings.effective_dsn())
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
        """Rebuild the graph projection from Postgres (source of truth).

        Safe to call at any time — it overwrites the graph with the current
        Postgres state. Use after a container restart kills an in-flight
        project stage, or to resync after manual DB edits.

        CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T11 follow-up: this always
        rebuilt a FalkorStore graph, regardless of the deployment's actual
        configured backend -- a real-data-confirmed no-op on any OCI/Oracle
        Graph deployment (ARYX_GRAPH_BACKEND=oci_graph), silently leaving
        the real graph (Oracle) untouched while claiming success. Mirrors
        orchestrate.py's own effective_graph_backend() dispatch so this
        endpoint rebuilds whichever graph the deployment actually reads
        from at request time.
        """
        settings = get_settings()
        estore = EntityStore(settings.effective_dsn(), workspace_id)
        try:
            type_ancestors = _build_type_ancestors(settings.effective_dsn(), workspace_id)
            if settings.effective_graph_backend() == "oci_graph":
                try:
                    from aryx.graph.oracle_graph_store import OracleGraphStore  # optional OCI dep
                    graph_inst = OracleGraphStore(settings.oci_adb_dsn, workspace_id)
                except ImportError as exc:
                    raise HTTPException(
                        503,
                        "ARYX_GRAPH_BACKEND=oci_graph but aryx.graph.oracle_graph_store is not "
                        "installed. Install the oci extras or unset ARYX_GRAPH_BACKEND.",
                    ) from exc
            else:
                graph_inst = FalkorStore(settings.graph_url, ws_graph(workspace_id))
            counts = project_graph(
                estore,
                graph_inst,
                type_ancestors=type_ancestors,
                workspace_id=workspace_id,
            )
        finally:
            estore.close()
        logger.info("manual graph rebuild workspace=%s counts=%s", workspace_id, counts)
        return {"status": "ok", "workspace_id": workspace_id, **counts}

    @router.get("/runs")
    def list_runs() -> list[dict[str, Any]]:
        # get_pool() (not a raw psycopg.connect()) so this also works on the
        # Oracle backend -- found by post-merge review: a hardcoded psycopg
        # connection can never reach Oracle regardless of which DSN it's
        # given. The query itself has no Postgres-only syntax, so no
        # translation/Oracle override is needed, just a backend-aware pool.
        settings = get_settings()
        with get_pool(settings.effective_dsn()).connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT run_id, source_system, source_dataset, status, "
                    "record_count, started_at, finished_at "
                    "FROM aryx_run ORDER BY run_id DESC LIMIT 50"
                )
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]

    return router
