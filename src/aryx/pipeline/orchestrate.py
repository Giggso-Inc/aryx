"""End-to-end pipeline orchestration (Increment 7): source -> graph.

Chains the existing stages into one runnable flow: discover (extract/clean/
profile/land, + cheap-tier tag when enabled) -> resolve landed records into
canonical entities -> optional frontier relationship inference -> project to
FalkorDB. The LLM stages (tag, relate) are opt-in, so the deterministic spine
runs end-to-end without any model configured.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.connectors.base import Connector
from aryx.discover import discover
from aryx.graph import FalkorStore
from aryx.naming import ws_graph
from aryx.models import OntologyType
from aryx.raven_log import raven_log
from aryx.resolution.stats import pop as _pop_stats
from aryx.pipeline.cooccurrence_link import detect_and_link_cooccurrence
from aryx.pipeline.dimension_link.dimension_link import detect_and_link_dimensions
from aryx.pipeline.enrich.enrich import _build_type_ancestors, _infer_schema_fk_links, _relate, _relate_isolated
from aryx.pipeline.fk_edges import link_by_attribute
from aryx.pipeline.stages import StageRunner
from aryx.store.checkpoint_store import StageTracker
from aryx.project import project_auto
from aryx.resolve_entities import resolve_run
from aryx.store.entity_store import EntityStore
from aryx.store.ontology_store import OntologyStore
from aryx.store.postgres_store import PostgresStore
from aryx.store.projection_store import ProjectionStore

logger = logging.getLogger(__name__)

Progress = Callable[[str, int, str], None]
ShouldStop = Callable[[], bool]

_FK_REQUIRED: frozenset[str] = frozenset({"source_type", "source_attr", "target_type", "target_attr"})


class PipelineCancelled(Exception):
    """Raised internally when `should_stop()` reports a cancelled job.

    Caught by the caller (file_ingest_api.py's _run_files) to end the
    worker thread cleanly instead of running the remaining stages to
    completion -- see make_should_stop's docstring for the bug this fixes.

    run_id: optional (PR #429 review N1, cpq_ingestion's raw-graph
    resolve/relate cancellation cleanup) -- when _check_cancelled raises
    this from inside run_pipeline(), the run_id whose records/entities were
    already created before the cancel fired. A cancel at the "relate"
    checkpoint lands right after resolve_cluster's entities are already
    saved; a catcher that wants to roll those back needs this run_id to
    find them (resolve_and_relate_raw_graph() otherwise learns a tag's
    run_id only after run_pipeline returns successfully, which a raise
    means never happens). None for every other raise site in the codebase,
    which don't need it.
    """

    def __init__(self, message: str, *, run_id: int | None = None) -> None:
        super().__init__(message)
        self.run_id = run_id


def _emit(cb: Progress | None, stage: str, pct: int, detail: str) -> None:
    """Report a pipeline stage to an optional progress callback."""
    if cb is not None:
        cb(stage, pct, detail)


def _check_cancelled(should_stop: ShouldStop | None, stage: str, run_id: int | None = None) -> None:
    """Raise PipelineCancelled if the job was cancelled mid-run.

    Called at every stage boundary (cheap: should_stop() itself throttles
    the underlying DB read, see make_should_stop) so a cancel takes effect
    within one stage instead of running the whole remaining pipeline.

    run_id: forwarded onto the raised PipelineCancelled (see its own
    docstring) -- every call site in run_pipeline() below already has this
    run's run_id in scope, so passing it costs nothing and lets a caller
    that cares (cpq_ingestion's resolve_and_relate_raw_graph) find and roll
    back this run's entities after a cancel at this checkpoint.
    """
    if should_stop is not None and should_stop():
        raven_log("WARN", "P3", "ingest.pipeline.cancelled job cancelled at stage boundary",
                  error_code="ARYX_ING_CANCELLED",
                  context={"stage": stage, "selected_option": "cancel", "available_options": ["continue", "cancel"],
                           "reason_code": "SHOULD_STOP_TRUE", "final_status": "cancelled"})
        raise PipelineCancelled(f"job cancelled before stage={stage}", run_id=run_id)
    raven_log("DEBUG", "P4", "ingest.pipeline.cancel_check not cancelled, continuing",
              context={"stage": stage, "selected_option": "continue",
                       "available_options": ["continue", "cancel"], "reason_code": "NOT_CANCELLED",
                       "has_should_stop": should_stop is not None})


def project_workspace_graph(
    dsn: str, graph_url: str, workspace_id: int, estore: EntityStore,
    *, on_progress: Progress | None = None,
) -> dict[str, int]:
    """Project every resolved entity/relationship in a workspace to its graph store.

    Factored out of ``run_pipeline``'s own project stage (below) so a caller
    that resolves entities outside run_pipeline's own connector/discover
    flow -- e.g. cpq_ingestion's raw-graph resolve/relate bridge, which runs
    one resolve per XML tag rather than one per file, then needs a single
    final projection once all tags are done -- can trigger the same, one
    tested graph projection instead of re-deriving the FalkorStore/
    OracleGraphStore selection and ``project_auto`` call itself.
    """
    logger.info("project stage — building type ancestors ws=%s", workspace_id)
    _pop_stats(("project", workspace_id))  # reset per-call markers (cleared / incremental)
    _t0 = time.monotonic()
    type_ancestors = _build_type_ancestors(dsn)
    cfg = get_settings()
    backend = cfg.effective_graph_backend()
    if backend == "oci_graph":
        raven_log("DEBUG", "P4", "ingest.project.backend_chosen graph backend: oci_graph",
                  context={"stage": "project", "workspace_id": workspace_id, "selected_option": "oci_graph",
                           "available_options": ["oci_graph", "falkordb"],
                           "reason_code": "EFFECTIVE_GRAPH_BACKEND_OCI_GRAPH",
                           "type_ancestors": len(type_ancestors or {})})
        try:
            from aryx.graph.oracle_graph_store import OracleGraphStore  # optional OCI dep
            graph_inst = OracleGraphStore(cfg.oci_adb_dsn, workspace_id)
        except ImportError as exc:
            raise RuntimeError(
                "ARYX_GRAPH_BACKEND=oci_graph but aryx.graph.oracle_graph_store is not "
                "installed. Install the oci extras or unset ARYX_GRAPH_BACKEND."
            ) from exc
    else:
        raven_log("DEBUG", "P4", "ingest.project.backend_chosen graph backend: falkordb",
                  context={"stage": "project", "workspace_id": workspace_id, "selected_option": "falkordb",
                           "available_options": ["oci_graph", "falkordb"],
                           "reason_code": "EFFECTIVE_GRAPH_BACKEND_NOT_OCI_GRAPH",
                           "type_ancestors": len(type_ancestors or {})})
        graph_inst = FalkorStore(graph_url, ws_graph(workspace_id))
    logger.info("project stage — calling project_auto ws=%s", workspace_id)
    pstore = ProjectionStore(dsn, workspace_id=workspace_id)
    try:
        counts = project_auto(
            estore, pstore, graph_inst,
            type_ancestors=type_ancestors, workspace_id=workspace_id,
            on_progress=on_progress, pct_range=(90, 95),
        )
    except Exception as exc:
        markers = _pop_stats(("project", workspace_id))
        raven_log("ERROR", "P1", "ingest.project.failed graph projection failed",
                  error_code="ARYX_ING_PROJECT_FAILED",
                  context={"stage": "project", "workspace_id": workspace_id, "backend": backend,
                           "graph_ref": getattr(graph_inst, "name", None) or getattr(graph_inst, "graph_name", None),
                           "mode": "incremental" if markers.get("incremental") else "full",
                           "cleared_before_failure": bool(markers.get("cleared")),
                           "final_status": "failed", "result": "error",
                           "error_class": type(exc).__name__, "dependency_name": "graph_store",
                           "duration_ms": int((time.monotonic() - _t0) * 1000),
                           "impact_scope": "workspace graph empty or partial; retrieval degraded"})
        raise
    markers = _pop_stats(("project", workspace_id))
    raven_log("INFO", "P4", "ingest.project.completed graph projection completed",
              context={"stage": "project", "workspace_id": workspace_id, "backend": backend,
                       "graph_ref": getattr(graph_inst, "name", None) or getattr(graph_inst, "graph_name", None),
                       "mode": "incremental" if markers.get("incremental") else "full",
                       "final_status": "done", "result": "ok",
                       "duration_ms": int((time.monotonic() - _t0) * 1000), "counts": dict(counts or {})})
    return counts


def run_pipeline(
    connector: Connector,
    dsn: str,
    system: str,
    dataset: str,
    ontology_type: str,
    match_keys: list[str],
    graph_url: str,
    broker: Broker,
    tag: bool = False,
    relate: bool = False,
    max_pairs: int | None = None,
    on_progress: Progress | None = None,
    fk_links: list[dict] | None = None,
    workspace_id: int = 1,
    resume_run_id: int | None = None,
    skip_graph: bool = False,
    should_stop: ShouldStop | None = None,
    force_exact: bool = False,
) -> dict[str, int]:
    """Run a source from extraction through to the FalkorDB projection.

    Args:
        connector: Configured source connector.
        dsn: Postgres DSN (the source of truth).
        system: Source system label.
        dataset: Source dataset/table label.
        ontology_type: Canonical type the records resolve into (pinned).
        match_keys: Payload keys whose values form the resolution match text.
        graph_url: FalkorDB connection URL.
        broker: Model broker (required by resolution; LLM only on opt-in stages).
        tag: Run cheap-tier field tagging during discovery.
        relate: Infer relationships between resolved entities (frontier tier).
        max_pairs: Cap on candidate pairs when relate is enabled (default: ARYX_MAX_RELATE_PAIRS).
        resume_run_id: Resume a crashed run — done stages skip, the landed
            data of that run is reused (no re-extract).
        force_exact: Forwarded to resolve_run() (§1 Tier 2, 2026-10-04) —
            caller-asserted override for when it already knows the match
            key's values are exact identifiers even though the key name
            itself doesn't look ID-like.

    Returns:
        Summary of {run_id, entities, relationships} plus graph projection counts.
    """
    _max_pairs = max_pairs if max_pairs is not None else get_settings().max_relate_pairs
    if resume_run_id is not None:
        run_id = resume_run_id
        runner = StageRunner(dsn, run_id, resume=True)
        logger.info("resuming run_id=%s", run_id)
        raven_log("INFO", "P4", "ingest.pipeline.start resuming run (no re-extract)",
                  context={"task_id": run_id, "selected_option": "resume",
                           "available_options": ["resume", "discover"], "reason_code": "RESUME_RUN_ID_GIVEN",
                           "workspace_id": workspace_id, "ontology_type": ontology_type,
                           "relate": bool(relate), "tag": bool(tag), "skip_graph": bool(skip_graph),
                           "max_pairs": _max_pairs, "fk_specs": len(fk_links or []),
                           "match_keys": list(match_keys)})
    else:
        raven_log("INFO", "P4", "ingest.pipeline.start new run: discover first",
                  context={"selected_option": "discover", "available_options": ["resume", "discover"],
                           "reason_code": "NO_RESUME_RUN_ID", "workspace_id": workspace_id,
                           "ontology_type": ontology_type, "relate": bool(relate), "tag": bool(tag),
                           "skip_graph": bool(skip_graph), "max_pairs": _max_pairs,
                           "fk_specs": len(fk_links or []), "match_keys": list(match_keys)})
        _emit(on_progress, "Discover", 5, "Starting extraction from source")
        store = PostgresStore(dsn, workspace_id)
        try:
            run_id = discover(connector, store, system, dataset,
                              broker=broker if tag else None,
                              on_progress=on_progress)
        finally:
            store.close()
        runner = StageRunner(dsn, run_id, resume=False)
        tracker = StageTracker(dsn)
        tracker.start(run_id, "discover")
        tracker.finish(run_id, "discover")

    estore = EntityStore(dsn, workspace_id)
    entities = relationships = 0
    counts: dict[str, int] = {}
    try:
        if not runner.skip("resolve_cluster"):
            _emit(on_progress, "Resolve", 30, "Loading landed records for resolution")
            with runner.stage("resolve_cluster"):
                entities = resolve_run(run_id, ontology_type, match_keys,
                                       estore, broker, on_progress=on_progress,
                                       workspace_id=workspace_id, force_exact=force_exact)
            _emit(on_progress, "Resolve", 62, f"{entities} entities resolved")
        # Register the type in OntologyStore so the schema diagram populates.
        # seed_types is idempotent (ON CONFLICT DO NOTHING).
        _emit(on_progress, "Seed", 65, f"Registering ontology type {ontology_type}")
        try:
            onto = OntologyStore(dsn, workspace_id)
            try:
                onto.seed_types([OntologyType(
                    name=ontology_type, attributes=list(match_keys),
                    status="approved", source="pipeline",
                )])
            finally:
                onto.close()
        except Exception:  # noqa: BLE001 — non-critical, don't fail the pipeline
            logger.error("ontology type seed failed type=%s ws=%s", ontology_type, workspace_id, exc_info=True)
            raven_log("ERROR", "P2", "ingest.ontology.seed_failed ontology type seed failed, pipeline continues",
                      error_code="ARYX_ING_ONTOLOGY_SEED_FAILED",
                      context={"task_id": run_id, "stage": "seed", "ontology_type": ontology_type,
                               "workspace_id": workspace_id, "result": "error",
                               "reason_code": "SEED_EXCEPTION_SWALLOWED", "impact_scope": "schema diagram"})
        _check_cancelled(should_stop, "relate", run_id=run_id)
        if relate and not runner.skip("relate"):
            _emit(on_progress, "Relate", 70, "Inferring relationships between entities")
            with runner.stage("relate"):
                relationships = _relate(estore, broker, _max_pairs)
        # Entities for FK linking are fetched ONCE and shared across both loops
        # below (schema_fk + fk_link) -- link_by_attribute used to re-fetch the
        # whole workspace per spec, which dominated the Link stage's runtime
        # (see docs/SCALABILITY_BOTTLENECKS.md P8). Neither loop creates new
        # entities, only relationships, so one snapshot is valid for both.
        link_entities: list[tuple[int, str, dict]] | None = None
        _check_cancelled(should_stop, "schema_fk", run_id=run_id)
        if relate and not runner.skip("schema_fk"):
            # Schema-level LLM FK inference: ONE call across ALL type schemas.
            # Finds shared-value joins that have no _id/_name suffix pattern
            # and were not covered by the entity-pair sample.
            # link_by_attribute then creates edges for ALL matching entities.
            _emit(on_progress, "Link", 78, "Discovering schema-level FK links")
            with runner.stage("schema_fk"):
                schema_links = _infer_schema_fk_links(estore, broker)
                if schema_links and link_entities is None:
                    link_entities = list(estore.list_entities())
                for spec in schema_links:
                    if not _FK_REQUIRED.issubset(spec):
                        logger.warning("schema_fk: skipping incomplete FK spec: %s", spec)
                        raven_log("WARN", "P3", "ingest.fk.spec_skipped schema_fk spec incomplete, skipped",
                                  error_code="ARYX_ING_FK_SPEC_INCOMPLETE",
                                  context={"task_id": run_id, "stage": "schema_fk", "selected_option": "skip",
                                           "available_options": ["link", "skip"], "reason_code": "MISSING_REQUIRED_FIELDS",
                                           "missing": sorted(_FK_REQUIRED - set(spec))})
                        continue
                    rel_name = spec.get(
                        "name",
                        f"{spec['source_type'].upper()}_LINKS_{spec['target_type'].upper()}",
                    )
                    relationships += link_by_attribute(
                        estore, link_entities, spec["source_type"], spec["source_attr"],
                        spec["target_type"], spec["target_attr"], rel_name,
                    )
            _emit(on_progress, "Relate", 78, f"{relationships} relationships inferred")
        _check_cancelled(should_stop, "fk_link", run_id=run_id)
        if fk_links and not runner.skip("fk_link"):
            _emit(on_progress, "Link", 80, f"Linking entities via {len(fk_links)} FK spec(s)")
            with runner.stage("fk_link"):
                if link_entities is None:
                    link_entities = list(estore.list_entities())
                for spec in fk_links:
                    if not _FK_REQUIRED.issubset(spec):
                        logger.warning("fk_link: skipping incomplete FK spec: %s", spec)
                        raven_log("WARN", "P3", "ingest.fk.spec_skipped fk_link spec incomplete, skipped",
                                  error_code="ARYX_ING_FK_SPEC_INCOMPLETE",
                                  context={"task_id": run_id, "stage": "fk_link", "selected_option": "skip",
                                           "available_options": ["link", "skip"], "reason_code": "MISSING_REQUIRED_FIELDS",
                                           "missing": sorted(_FK_REQUIRED - set(spec))})
                        continue
                    rel_name = spec.get(
                        "name",
                        f"{spec['source_type'].upper()}_LINKS_{spec['target_type'].upper()}",
                    )
                    relationships += link_by_attribute(
                        estore, link_entities, spec["source_type"], spec["source_attr"],
                        spec["target_type"], spec["target_attr"], rel_name,
                    )
        _check_cancelled(should_stop, "cooccurrence_link", run_id=run_id)
        if not skip_graph and not runner.skip("cooccurrence_link"):
            # Tier-0 deterministic linking, document sources only: connects
            # entities extracted from the SAME chunk of text — a real,
            # cheap signal tabular data has no equivalent of, and one FK
            # detection/dimension linking/the LLM safety net all miss
            # entirely for free text. Runs before relate_isolated so that
            # pass has fewer isolated entities left to spend LLM calls on.
            # Safe no-op for tabular/XML sources (no chunk_index attribute).
            _emit(on_progress, "Link", 87, "Linking entities mentioned in the same passage")
            with runner.stage("cooccurrence_link"):
                relationships += detect_and_link_cooccurrence(estore)
        _check_cancelled(should_stop, "relate_isolated", run_id=run_id)
        if not skip_graph and not runner.skip("relate_isolated"):
            # Final safety net: any entity still isolated after FK linking and
            # sampled-pair inference gets one LLM call against the nearest anchor.
            # Enforces the rule: no FK link -> LLM inference, for any file type.
            # Deliberately NOT gated on `relate` — this is what guarantees zero
            # isolated nodes, so it must run even when the best-effort _relate()
            # pass above was skipped (ARYX_INGEST_RELATE=false) or only partially
            # completed (e.g. it hit relate_pair_timeout on a stuck LLM call).
            # _relate_isolated() is self-contained (queries isolated entities
            # itself) and a safe no-op when nothing is isolated.
            #
            # IS gated on skip_graph, unlike `relate` above: a real incident
            # with 96 plans in one batch showed this running — and re-querying
            # every isolated entity in the whole workspace, plus fresh LLM
            # calls — on every non-final plan, even though skip_graph means
            # none of that plan's state is ever projected until the final
            # plan runs. The final plan's own call already re-scans ALL
            # entities from every earlier plan, so it alone guarantees the
            # zero-isolated-nodes contract; the intermediate calls were
            # strictly wasted work, not additional coverage.
            _emit(on_progress, "Link", 88, "Connecting remaining isolated entities")
            with runner.stage("relate_isolated"):
                relationships += _relate_isolated(estore, broker, should_stop=should_stop)
        _check_cancelled(should_stop, "dimension_link", run_id=run_id)
        if not skip_graph and not runner.skip("dimension_link"):
            # Tier-2 deterministic linking: connect entity types that share a
            # low-cardinality dimension (state, fiscal period, category code)
            # but have no row-level key, via a shared hub entity. Runs once,
            # on the final plan, after FK linking and the LLM safety net —
            # by that point every entity that COULD be linked to a specific
            # other entity already is; this only ever adds coverage for
            # entities still isolated, so it must run last, before projection.
            #
            # should_stop is threaded all the way into the inner value/entity
            # loop (not just checked at this stage boundary) -- this was the
            # actual runaway stage observed live: a cancelled job kept
            # creating Dimension:* entities for 20+ minutes, since nothing
            # inside the loop itself ever re-checked cancellation.
            _emit(on_progress, "Link", 89, "Linking shared dimensions (state, period, category)")
            with runner.stage("dimension_link"):
                relationships += detect_and_link_dimensions(estore, should_stop=should_stop)
        _check_cancelled(should_stop, "project", run_id=run_id)
        if not skip_graph:
            _emit(on_progress, "Project", 90, "Projecting entities and edges to the graph")
            with runner.stage("project"):
                counts = project_workspace_graph(dsn, graph_url, workspace_id, estore,
                                                 on_progress=on_progress)
        else:
            logger.debug("skip_graph=True — FalkorDB projection deferred to final plan")
            raven_log("INFO", "P4", "ingest.project.deferred projection deferred to final plan",
                      context={"task_id": run_id, "stage": "project", "selected_option": "defer",
                               "available_options": ["project", "defer"], "reason_code": "SKIP_GRAPH_TRUE"})
            _emit(on_progress, "Project", 95, f"Graph updated — {counts.get('entities', 0)} nodes, {counts.get('relationships', 0)} edges")
    finally:
        estore.close()

    summary = {"run_id": run_id, "entities": entities,
               "relationships": relationships, **counts}
    _emit(on_progress, "Done", 100, f"{entities} entities · {relationships} relationships · {counts.get('entities', 0)} graph nodes")
    logger.info("pipeline complete %s", summary)
    raven_log("INFO", "P4", "ingest.pipeline.completed pipeline finished",
              context={"task_id": run_id, "stage": "done", "final_status": "complete", "result": "ok",
                       "entities": entities, "relationships": relationships,
                       "graph_counts": dict(counts), "workspace_id": workspace_id})
    return summary
