"""End-to-end pipeline orchestration (Increment 7): source -> graph.

Chains the existing stages into one runnable flow: discover (extract/clean/
profile/land, + cheap-tier tag when enabled) -> resolve landed records into
canonical entities -> optional frontier relationship inference -> project to
FalkorDB. The LLM stages (tag, relate) are opt-in, so the deterministic spine
runs end-to-end without any model configured.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.connectors.base import Connector
from aryx.discover import discover
from aryx.graph import FalkorStore
from aryx.naming import ws_graph
from aryx.models import OntologyType
from aryx.pipeline.cooccurrence_link import detect_and_link_cooccurrence
from aryx.pipeline.dimension_link import detect_and_link_dimensions
from aryx.pipeline.enrich import _build_type_ancestors, _infer_schema_fk_links, _relate, _relate_isolated
from aryx.pipeline.fk_edges import link_by_attribute
from aryx.pipeline.stages import StageRunner
from aryx.store.checkpoint_store import StageTracker
from aryx.project import project_graph
from aryx.resolve_entities import resolve_run
from aryx.store.entity_store import EntityStore
from aryx.store.ontology_store import OntologyStore
from aryx.store.postgres_store import PostgresStore

logger = logging.getLogger(__name__)

Progress = Callable[[str, int, str], None]

_FK_REQUIRED: frozenset[str] = frozenset({"source_type", "source_attr", "target_type", "target_attr"})


def _emit(cb: Progress | None, stage: str, pct: int, detail: str) -> None:
    """Report a pipeline stage to an optional progress callback."""
    if cb is not None:
        cb(stage, pct, detail)


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

    Returns:
        Summary of {run_id, entities, relationships} plus graph projection counts.
    """
    _max_pairs = max_pairs if max_pairs is not None else get_settings().max_relate_pairs
    if resume_run_id is not None:
        run_id = resume_run_id
        runner = StageRunner(dsn, run_id, resume=True)
        logger.info("resuming run_id=%s", run_id)
    else:
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
                                       workspace_id=workspace_id)
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
            logger.warning("ontology type seed failed for %s", ontology_type, exc_info=True)
        if relate and not runner.skip("relate"):
            _emit(on_progress, "Relate", 70, "Inferring relationships between entities")
            with runner.stage("relate"):
                relationships = _relate(estore, broker, _max_pairs)
        if relate and not runner.skip("schema_fk"):
            # Schema-level LLM FK inference: ONE call across ALL type schemas.
            # Finds shared-value joins that have no _id/_name suffix pattern
            # and were not covered by the entity-pair sample.
            # link_by_attribute then creates edges for ALL matching entities.
            _emit(on_progress, "Link", 78, "Discovering schema-level FK links")
            with runner.stage("schema_fk"):
                schema_links = _infer_schema_fk_links(estore, broker)
                for spec in schema_links:
                    if not _FK_REQUIRED.issubset(spec):
                        logger.warning("schema_fk: skipping incomplete FK spec: %s", spec)
                        continue
                    rel_name = spec.get(
                        "name",
                        f"{spec['source_type'].upper()}_LINKS_{spec['target_type'].upper()}",
                    )
                    relationships += link_by_attribute(
                        estore, spec["source_type"], spec["source_attr"],
                        spec["target_type"], spec["target_attr"], rel_name,
                    )
            _emit(on_progress, "Relate", 78, f"{relationships} relationships inferred")
        if fk_links and not runner.skip("fk_link"):
            _emit(on_progress, "Link", 80, f"Linking entities via {len(fk_links)} FK spec(s)")
            with runner.stage("fk_link"):
                for spec in fk_links:
                    if not _FK_REQUIRED.issubset(spec):
                        logger.warning("fk_link: skipping incomplete FK spec: %s", spec)
                        continue
                    rel_name = spec.get(
                        "name",
                        f"{spec['source_type'].upper()}_LINKS_{spec['target_type'].upper()}",
                    )
                    relationships += link_by_attribute(
                        estore, spec["source_type"], spec["source_attr"],
                        spec["target_type"], spec["target_attr"], rel_name,
                    )
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
                relationships += _relate_isolated(estore, broker)
        if not skip_graph and not runner.skip("dimension_link"):
            # Tier-2 deterministic linking: connect entity types that share a
            # low-cardinality dimension (state, fiscal period, category code)
            # but have no row-level key, via a shared hub entity. Runs once,
            # on the final plan, after FK linking and the LLM safety net —
            # by that point every entity that COULD be linked to a specific
            # other entity already is; this only ever adds coverage for
            # entities still isolated, so it must run last, before projection.
            _emit(on_progress, "Link", 89, "Linking shared dimensions (state, period, category)")
            with runner.stage("dimension_link"):
                relationships += detect_and_link_dimensions(estore)
        if not skip_graph:
            _emit(on_progress, "Project", 90, "Projecting entities and edges to the graph")
            with runner.stage("project"):
                type_ancestors = _build_type_ancestors(dsn)
                cfg = get_settings()
                if cfg.effective_graph_backend() == "oci_graph":
                    try:
                        from aryx.graph.oracle_graph_store import OracleGraphStore  # optional OCI dep
                        graph_inst = OracleGraphStore(cfg.oci_adb_dsn, workspace_id)
                    except ImportError as exc:
                        raise RuntimeError(
                            "ARYX_GRAPH_BACKEND=oci_graph but aryx.graph.oracle_graph_store is not "
                            "installed. Install the oci extras or unset ARYX_GRAPH_BACKEND."
                        ) from exc
                else:
                    graph_inst = FalkorStore(graph_url, ws_graph(workspace_id))
                counts = project_graph(
                    estore, graph_inst,
                    type_ancestors=type_ancestors, workspace_id=workspace_id,
                    on_progress=on_progress, pct_range=(90, 95),
                )
        else:
            logger.debug("skip_graph=True — FalkorDB projection deferred to final plan")
            _emit(on_progress, "Project", 95, f"Graph updated — {counts.get('entities', 0)} nodes, {counts.get('relationships', 0)} edges")
    finally:
        estore.close()

    summary = {"run_id": run_id, "entities": entities,
               "relationships": relationships, **counts}
    _emit(on_progress, "Done", 100, f"{entities} entities · {relationships} relationships · {counts.get('entities', 0)} graph nodes")
    logger.info("pipeline complete %s", summary)
    return summary
