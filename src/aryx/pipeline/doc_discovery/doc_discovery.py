"""Document self-discovery: read files, surface discovered types, ingest on OK.

Reading runs the document pipeline (chunk → PII → embed → extract) and keeps
each mention's *own* discovered type instead of pinning one. Tabular files
(JSON/CSV) get a single type inferred from a sample. Nothing lands until the
user confirms which types to keep.

As of the Raven Style Compliance Plan's Phase 2a (2026-09-03): type/match-key
inference lives in `pipeline.doc_discovery_types`, XML parsing in `pipeline.
doc_discovery_xml`, XLSX parsing in `pipeline.doc_discovery_xlsx`, CSV name
consolidation in `pipeline.doc_discovery_csv`, column-name FK detection in
`pipeline.doc_discovery_fk`, and source-catalog persistence in `pipeline.
doc_discovery_persist` — all re-imported here. `read_files` and `ingest_
confirmed` stay in this hub because they are the sole callers of several
directly whitebox-patched names (`_infer_type`, `_detect_fk_links`, `_detect_
script_data_flow_links`, `_detect_fk_links_workspace`, `_persist_tabular_
sources` — patched as `aryx.pipeline.doc_discovery.doc_discovery.<name>` across `test_doc_
discovery.py`, `test_ingest_confirmed_fk_detection_progress.py`, and `test_
ingest_confirmed_mentions_batching.py`); importing the real implementations
here and calling them by bare name keeps every one of those patches
intercepting correctly.
"""
from __future__ import annotations

import csv
import io
import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tempfile import NamedTemporaryFile
from collections.abc import Callable
from typing import Any

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.connectors.csv_source import CsvConnector
from aryx.connectors.doc_router import DocumentRouterConnector
from aryx.connectors.json_source import JsonConnector
from aryx.connectors.records_source import RecordsConnector
from aryx.pipeline.doc_discovery.doc_discovery_csv import _consolidate_csv_names
from aryx.pipeline.doc_discovery.doc_discovery_fk import (
    _detect_fk_links,
    _detect_fk_links_workspace,
    _detect_script_data_flow_links,
)
from aryx.pipeline.doc_discovery.doc_discovery_persist import _persist_tabular_sources
from aryx.pipeline.doc_discovery.doc_discovery_types import _infer_type, _singular, _stem_type
from aryx.pipeline.doc_discovery.doc_discovery_xlsx import _sheet_slug, _xlsx_to_csvs
from aryx.pipeline.doc_discovery.doc_discovery_xml import _xml_to_csvs
from aryx.pipeline.dynamic_fk.dynamic_fk import detect_dynamic_fk_links
from aryx.pipeline.orchestrate import run_pipeline
from aryx.store.chunk_store import ChunkStore
from aryx.store.datasource_store import DatasourceStore
from aryx.store.ontology_store import OntologyStore
from aryx.source.source_catalog import restore_generic_source_entry

__all__ = [
    "DATA_EXTS",
    "DOC_EXTS",
    "_consolidate_csv_names",
    "_detect_fk_links",
    "_detect_fk_links_workspace",
    "_detect_script_data_flow_links",
    "_infer_type",
    "_persist_tabular_sources",
    "_sheet_slug",
    "_singular",
    "_stem_type",
    "_xlsx_to_csvs",
    "_xml_to_csvs",
    "ingest_confirmed",
    "read_files",
]

logger = logging.getLogger(__name__)

DOC_EXTS = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".rtf",
            ".html", ".htm",
            ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"}
DATA_EXTS = {".json", ".csv", ".xml", ".xlsx"}


def read_files(doc_paths: list[Path], tabular: list[tuple[bytes, str]],
               broker: Broker, context: str, did: str | None = None,
               on_progress: Callable[[int, int, list], None] | None = None,
               workspace_id: int = 1) -> dict[str, Any]:
    """Read everything; return {mentions, tabular, summary} without committing.

    on_progress: optional callback forwarded to extract_mentions() for each
    document — see doc_router.DocumentRouterConnector / ontology.extract for
    the (completed, total, new_records) signature. Lets the caller persist
    partial progress on long-running (1000+ page) documents.

    workspace_id: forwarded to the cpq_ingestion raw-graph writer for XML
    files when that pipeline is active (ARYX_INGEST_FILE_TYPE/ARYX_INGEST_
    PIPELINE) — see the XML branch below. Unused otherwise; defaults to 1
    to match every other call site's pre-existing default.
    """
    settings = get_settings()
    logger.info("read_files start did=%s doc_files=%d tabular_files=%d context=%r",
                did, len(doc_paths), len(tabular), context)
    mentions = []
    if doc_paths:
        connector = DocumentRouterConnector(
            paths=doc_paths, system="document", broker=broker,
            chunk_store=ChunkStore(settings.effective_dsn()), chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap, expected_embed_dim=settings.embed_dim,
            context=context, on_progress=on_progress)
        mentions = list(connector.extract())

    # XML/XLSX files: expand into one CSV per element type / worksheet so
    # that _detect_fk_links can wire cross-type relationships automatically.
    # CSV files: apply name-field consolidation for multi-part name columns.
    converted_tabular = []
    for d, n in tabular:
        suffix = Path(n).suffix.lower()
        if suffix == ".xml":
            # Lazy import: aryx.cpq_ingestion.pipeline itself imports
            # _xml_to_csvs from this module, so a top-level import here
            # would be circular.
            from aryx.cpq_ingestion.pipeline import project_raw_graph_and_flatten  # noqa: PLC0415
            from aryx.cpq_ingestion.routing import cpq_ingestion_pipeline_active  # noqa: PLC0415

            if cpq_ingestion_pipeline_active(n):
                xml_csvs = project_raw_graph_and_flatten(
                    d, Path(n).stem, workspace_id=workspace_id,
                    dsn=settings.effective_dsn(), graph_url=settings.graph_url, log_id=did,
                )
            else:
                xml_csvs = _xml_to_csvs(d, Path(n).stem, log_id=did)
            for csv_bytes, csv_name in xml_csvs:
                converted_tabular.append((csv_bytes, csv_name, n, d))
        elif suffix == ".xlsx":
            for csv_bytes, csv_name in _xlsx_to_csvs(d, Path(n).stem, log_id=did):
                converted_tabular.append((csv_bytes, csv_name, n, d))
        else:
            converted_tabular.append((_consolidate_csv_names(d, did=did), n, None, None))

    tab_plans = []
    for data, filename, source_filename, source_bytes in converted_tabular:
        inferred = _infer_type(data[:800].decode("utf-8", "ignore"), filename, context, did=did)
        plan = {"filename": filename, "data": data, **inferred}
        if source_filename is not None and source_bytes is not None:
            plan["source_filename"] = source_filename
            plan["source_bytes"] = source_bytes
            try:
                headers = next(csv.reader(io.StringIO(data.decode("utf-8", "ignore"))))
            except Exception:  # noqa: BLE001
                headers = []
            if "_text" in headers:
                plan["match_keys"] = ["_text"]
        tab_plans.append(plan)

    by_type: dict[str, list[str]] = {}
    for m in mentions:
        by_type.setdefault(m.payload["type"], []).append(m.payload["name"])
    types = [{"type": t, "count": len(v), "examples": list(dict.fromkeys(v))[:5]}
             for t, v in sorted(by_type.items(), key=lambda kv: -len(kv[1]))]
    files = [{"filename": p["filename"], "ontology_type": p["ontology_type"]} for p in tab_plans]
    logger.info("read_files done did=%s mentions=%d tabular_plans=%d types=%d files=%d",
                did, len(mentions), len(tab_plans), len(types), len(files))
    return {"mentions": mentions, "tabular": tab_plans,
            "summary": {"types": types, "files": files}}


def _update_confirm_state(discovery_id: str, state: dict) -> None:
    """Persist confirm_state to DB after each plan (crash-safe resume support)."""
    from aryx.store.discovery_store import DiscoveryStore  # noqa: PLC0415 — lazy to avoid circular
    settings = get_settings()
    store = DiscoveryStore(settings.effective_dsn())
    try:
        store.update_confirm_state(discovery_id, state)
    finally:
        store.close()


def ingest_confirmed(data: dict[str, Any], approved_types: list[str],
                     approved_files: list[str], broker: Broker, jobs, job_id: str,
                     workspace_id: int = 1,
                     confirm_state: dict | None = None,
                     discovery_id: str | None = None) -> None:
    """Resolve + project the approved discovered types and tabular files.

    confirm_state enables crash-safe resume: completed plans are skipped and
    progress is persisted to DB after each plan so a restart picks up where
    it left off.
    """
    settings = get_settings()
    datasource_store = DatasourceStore(settings.effective_dsn())
    total = max(len(approved_types) + len(approved_files), 1)
    step = 0

    state = confirm_state or {}
    completed_plans: set[str] = set(state.get("completed_plans", []))
    plan_run_ids: dict[str, str] = dict(state.get("plan_run_ids", {}))

    # Same is_last/skip_graph pattern already used below for tabular plans
    # (see _run_one_plan): a real incident with 96 mention types on one PDF
    # showed every type's run_pipeline() call independently ran relate,
    # schema_fk, relate_isolated, dimension_link, AND project_graph — and
    # project_graph's own contract is to clear() and rebuild the ENTIRE
    # workspace graph from every entity seen so far, so cost grew with every
    # type instead of running once. Only the LAST type with any mentions
    # now runs the expensive whole-workspace passes; earlier types just
    # resolve their own records into entities.
    types_with_recs = [
        ot for ot in approved_types
        if any(m.payload.get("type") == ot for m in data["mentions"])
    ]
    last_type_with_recs = types_with_recs[-1] if types_with_recs else None

    for otype in approved_types:
        step += 1
        jobs.update_stage(job_id, f"{step}/{total}", int(step * 90 / total), f"Adding {otype}")
        recs = [m for m in data["mentions"] if m.payload.get("type") == otype]
        if recs:
            is_last = otype == last_type_with_recs
            logger.info("confirm job=%s step=%d/%d otype=%s records=%d is_last=%s",
                        job_id, step, total, otype, len(recs), is_last)

            def _progress_otype(stage: str, pct: int, detail: str, _otype: str = otype,
                                 _step: int = step) -> None:
                jobs.update_stage(job_id, f"{_step}/{total} · {stage}",
                                  int(_step * 90 / total) + pct // 10, detail)
                logger.info("confirm job=%s otype=%s stage=%s pct=%d %s",
                            job_id, _otype, stage, pct, detail)

            # TODO: pass job_id=job_id once run_pipeline supports it
            run_pipeline(connector=RecordsConnector(recs, label=otype), dsn=settings.effective_dsn(),
                         system="document", dataset=otype, ontology_type=otype,
                         match_keys=["name"], graph_url=settings.graph_url, broker=broker,
                         workspace_id=workspace_id, relate=is_last, skip_graph=not is_last,
                         on_progress=_progress_otype)
        else:
            logger.info("confirm job=%s step=%d/%d otype=%s skipped, no matching mentions",
                        job_id, step, total, otype)

    # Collect valid plans in approval order so FK detection sees the full picture.
    # Filter out already-completed plans when resuming.
    all_valid_plans = [p for p in
                       (next((p for p in data["tabular"] if p["filename"] == fn), None)
                        for fn in approved_files)
                       if p is not None]
    valid_plans = [p for p in all_valid_plans if p["filename"] not in completed_plans]
    if len(valid_plans) < len(all_valid_plans):
        logger.info("confirm job=%s resume: skipping %d completed plan(s): %s",
                    job_id, len(all_valid_plans) - len(valid_plans),
                    [p["filename"] for p in all_valid_plans if p["filename"] in completed_plans])
    _persist_tabular_sources(valid_plans, workspace_id, settings.effective_dsn())

    def _report_fk_stage(pct: int, detail: str) -> None:
        # A transient job-store failure while reporting progress must never
        # abort real FK-detection work — same discipline as dynamic_fk.py's
        # own on_progress guard (judge_candidates_with_llm).
        try:
            jobs.update_stage(job_id, "FK Detection", pct, detail)
        except Exception:  # noqa: BLE001
            logger.warning("confirm job=%s FK-detection stage report failed", job_id, exc_info=True)

    # docs/falkordb_high_cpu_2026-07-29.md follow-up — this whole FK-detection
    # block (column-name passes + the dynamic value-overlap/LLM-judge pass
    # below) previously called jobs.update_stage() nowhere at all. A
    # CSV-only confirm (no approved_types, so the mentions loop above never
    # runs either) sat at its initial jobs.create() values — status
    # "queued", pct 0 — for the entire duration of this block, genuinely
    # indistinguishable in the UI/API from a job that never started, even
    # though real work was running. Live-confirmed: a 33-file SL3500e batch
    # sat "queued" for 9+ minutes of real dynamic-FK activity.
    _report_fk_stage(1, "Detecting column-name foreign keys…")
    auto_fk = _detect_fk_links(valid_plans, log_id=job_id)
    if auto_fk:
        logger.info("confirm job=%s auto-detected %d fk-link spec(s): %s",
                    job_id, len(auto_fk), auto_fk)

    # Array-iteration BML idiom recognition (Approach B, docs/
    # CPQ_BML_ARRAY_ITERATION_TIER_PLAN.md) — additive, alongside the
    # column-name-based FK detection above. Mutates the bm_function plan's
    # own CSV data (adds 3 derived columns) when it finds recognized
    # scripts, so this must run before _run_one_plan below reads plan["data"].
    if valid_plans:
        _report_fk_stage(2, "Analyzing script data-flow links…")
    script_flow_links = _detect_script_data_flow_links(valid_plans, log_id=job_id)
    if script_flow_links:
        auto_fk.extend(script_flow_links)
        logger.info("confirm job=%s array-iteration script analysis: %d link spec(s): %s",
                    job_id, len(script_flow_links), script_flow_links)

    # Detect FK links from the last plan to types already in the workspace.
    # Fires for single-file jobs where _detect_fk_links returns [].
    if valid_plans:
        _report_fk_stage(3, "Detecting workspace-level foreign keys…")
        try:
            onto = OntologyStore(settings.effective_dsn(), workspace_id)
            try:
                known_types = [t.name for t in onto.list_types()]
            finally:
                onto.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("confirm job=%s OntologyStore lookup failed, skipping workspace FK "
                           "detection: %s", job_id, exc, exc_info=True)
            known_types = []
        existing_pairs: set[tuple[str, str]] = {
            (lk["source_type"], lk["target_type"]) for lk in auto_fk
        }
        workspace_fk = _detect_fk_links_workspace(
            valid_plans[-1], known_types, seen=existing_pairs, job_id=job_id
        )
        if workspace_fk:
            auto_fk.extend(workspace_fk)
            logger.info("confirm job=%s workspace FK links detected count=%d specs=%s",
                        job_id, len(workspace_fk), workspace_fk)

    # Dynamic (value-overlap + LLM judge) detection — fills the gap the
    # column-name passes above cannot see (differently-named columns,
    # derived/semantic joins). Runs once over the whole batch, only on pairs
    # not already resolved above, so it's purely additive.
    if valid_plans:
        _report_fk_stage(4, "Scanning for dynamic (value-overlap) foreign keys…")
        already_linked = {(lk["source_type"], lk["target_type"]) for lk in auto_fk}

        # -inf, not 0.0: the first call must always report regardless of
        # what time.monotonic()'s reference point happens to be (its epoch
        # is unspecified — could itself be near 0 depending on platform).
        _last_dynamic_fk_report = float("-inf")

        def _dynamic_fk_progress(done: int, total_candidates: int) -> None:
            # 5-10%: this stage alone can run for many minutes on a large
            # multi-table batch (every candidate gets its own LLM call, no
            # cap) — real "N/M judged" progress here is what would have
            # told us live whether the 9-minute-silent run was working or
            # actually hung, instead of guessing from CPU% and log gaps.
            #
            # Throttled (2026-09-23, docs/ingestion/SPARK_PARALLEL_MIGRATION_
            # ANALYSIS_2026-09-23.md Phase 2): live-measured, calling
            # _report_fk_stage() -> jobs.update_stage() (2 DB round-trips)
            # once per candidate made the progress WRITES themselves the
            # bottleneck once ARYX_FK_DYNAMIC_JUDGE_WORKERS was raised —
            # 2186 candidates at ~1.1s/write is ~40 minutes of pure
            # sequential DB round-trips on the main thread, regardless of
            # how many workers finish the actual LLM judging concurrently.
            # At the original default of 4 workers this was invisible
            # (LLM latency alone was already >1s/candidate, so the write
            # rode along inside it); it only became the dominant cost once
            # more workers made LLM latency faster than the write itself.
            # The final candidate always reports so the stage still ends
            # at an accurate 100%, not a stale intermediate count.
            nonlocal _last_dynamic_fk_report
            now = time.monotonic()
            is_last = done >= total_candidates
            min_interval = get_settings().fk_dynamic_progress_report_min_interval_s
            if not is_last and (now - _last_dynamic_fk_report) < min_interval:
                return
            _last_dynamic_fk_report = now
            pct = 5 + int(done * 5 / max(total_candidates, 1))
            _report_fk_stage(pct, f"Judging candidate foreign keys ({done}/{total_candidates})…")

        dynamic_fk = detect_dynamic_fk_links(
            valid_plans, broker, already_linked=already_linked, log_id=job_id,
            on_progress=_dynamic_fk_progress,
        )
        if dynamic_fk:
            auto_fk.extend(dynamic_fk)
            logger.info("confirm job=%s dynamic (value+LLM) fk-link spec(s): %d: %s",
                        job_id, len(dynamic_fk), dynamic_fk)

    def _run_one_plan(plan: dict, is_last: bool, plan_step: int) -> None:
        """Run a single tabular plan through the pipeline."""
        fname = plan["filename"]
        otype = plan["ontology_type"]
        logger.info("confirm job=%s step=%d/%d file=%s otype=%s is_last=%s",
                    job_id, plan_step, total, fname, otype, is_last)
        jobs.update_stage(job_id, f"{plan_step}/{total} · Discover",
                          int(plan_step * 90 / total), f"Starting {fname}")
        tmp_path: Path | None = None
        if Path(fname).suffix.lower() == ".json":
            tmp = NamedTemporaryFile(suffix=".json", delete=False)
            tmp.write(plan["data"])
            tmp.close()
            tmp_path = Path(tmp.name)
            conn = JsonConnector(tmp_path, system="json")
        else:
            conn = CsvConnector(plan["data"], system="csv", dataset=Path(fname).stem)

        def _progress_plan(stage: str, pct: int, detail: str) -> None:
            # Parallel plans share the job record — cap pct so we don't jump backwards.
            base = int(plan_step * 90 / total)
            jobs.update_stage(job_id, f"{plan_step}/{total} · {stage}",
                              min(base + pct // 10, 90), detail)
            logger.info("confirm job=%s file=%s stage=%s pct=%d %s",
                        job_id, fname, stage, pct, detail)

        try:
            # relate: only the last plan runs LLM inference — it can see ALL
            # entity types that were resolved by prior plans.  Non-last plans
            # run on a partial entity set and would produce spurious/incomplete
            # relationships that the final pass then can't correct.
            # skip_graph=True for non-last plans: project_graph calls graph.clear()
            # then rebuilds the entire workspace graph — concurrent calls race and
            # corrupt each other.  Only the final serial plan projects to FalkorDB;
            # it calls estore.list_entities() which covers ALL workspace entities.
            # TODO: pass job_id=job_id once run_pipeline supports it
            run_pipeline(connector=conn, dsn=settings.effective_dsn(),
                         system=Path(fname).suffix.lstrip("."), dataset=Path(fname).stem,
                         ontology_type=otype, match_keys=plan["match_keys"],
                         graph_url=settings.graph_url, broker=broker, workspace_id=workspace_id,
                         fk_links=auto_fk if is_last else None,
                         relate=is_last and settings.ingest_relate,
                         skip_graph=not is_last,
                         on_progress=_progress_plan)
            suffix = Path(fname).suffix.lower()
            if suffix in {".csv", ".json"}:
                restore_generic_source_entry(
                    datasource_store,
                    workspace_id=workspace_id,
                    source_system=suffix.lstrip("."),
                    source_dataset=Path(fname).stem,
                )
            logger.info("confirm job=%s file=%s done", job_id, fname)
            # Persist progress after each plan so a restart can resume here.
            if discovery_id:
                completed_plans.add(fname)
                _update_confirm_state(discovery_id, {
                    "last_job_id": job_id,
                    "completed_plans": list(completed_plans),
                    "plan_run_ids": plan_run_ids,
                    "failed_plans": [],
                })
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    # Non-last plans run in parallel — they don't apply FK links so ordering
    # between them doesn't matter.  The last plan runs serially after all
    # others complete so that link_by_attribute can see every prior entity.
    non_last = valid_plans[:-1]
    last = valid_plans[-1] if valid_plans else None
    plan_steps = {p["filename"]: step + i + 1 for i, p in enumerate(valid_plans)}

    jobs.update_stage(job_id, f"{step + 1}/{total}", int((step + 1) * 90 / total),
                      f"Ingesting {len(valid_plans)} file(s) ({settings.ingest_workers} parallel)…")
    logger.info("confirm job=%s ingesting files=%s fk_links=%d",
                job_id, [p["filename"] for p in valid_plans], len(auto_fk))

    if non_last:
        with ThreadPoolExecutor(max_workers=settings.ingest_workers) as pool:
            futs = {pool.submit(_run_one_plan, p, False, plan_steps[p["filename"]]): p["filename"]
                    for p in non_last}
            failed: list[str] = []
            for fut in as_completed(futs):
                fname_done = futs[fut]
                try:
                    fut.result()
                    logger.info("confirm job=%s plan complete file=%s", job_id, fname_done)
                except Exception:
                    logger.warning("confirm job=%s plan failed file=%s",
                                   job_id, fname_done, exc_info=True)
                    failed.append(fname_done)
            if failed:
                logger.warning(
                    "confirm job=%s skipping %d failed plan(s): %s — continuing with remaining",
                    job_id, len(failed), failed,
                )

    if last:
        last_step = plan_steps[last["filename"]]
        jobs.update_stage(job_id, f"{last_step}/{total} · FK links",
                          int(last_step * 90 / total), f"Finalising FK links for {last['filename']}…")
        _run_one_plan(last, is_last=True, plan_step=last_step)

    # Zero-loss validation: prove every source record reached the graph.
    # Best-effort by contract — validation surfaces problems, never fails the job.
    if valid_plans:
        try:
            from aryx.pipeline.ingest_validation.ingest_validation import (
                ground_truth_from_tabular, validate_workspace,
            )
            gt = ground_truth_from_tabular(valid_plans)
            report = validate_workspace(workspace_id, gt, settings.effective_dsn(),
                                        settings.graph_url)
            logger.info("confirm job=%s validation passed=%s %s",
                        job_id, report.passed, report.summary_line())
            for line in report.failures():
                logger.warning("confirm job=%s validation FAIL %s", job_id, line)
        except Exception as exc:  # noqa: BLE001 — never fail the ingest over validation
            logger.warning("confirm job=%s validation crashed: %s", job_id, exc,
                           exc_info=True)

    # docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md — the CPQ rule/
    # table caches (data_table_resolver._TABLES_CACHE, engine._VALUE_RULES_
    # CACHE/_RULE_JOIN_DATA_CACHE) were widened from a 30s to a 300s TTL to
    # let them survive real cross-turn gaps; that widening only stays safe
    # against a re-ingest changing this workspace's Data Tables/rules
    # mid-session if staleness is cleared HERE, at the point ingestion
    # actually completes, rather than relying on the (now longer) TTL alone
    # to eventually notice. These hooks clear() the WHOLE module-level cache
    # (no workspace-scoped variant exists — they're simple dicts keyed by
    # (workspace_id, catalog_prefix) with no per-key clear helper), so an
    # ingest into workspace A also evicts workspace B's still-warm cache
    # entries — a bounded, acceptable inefficiency (one extra fresh scan for
    # unrelated workspaces on their next turn), not a correctness issue.
    # Best-effort — an import failure or clear() bug must never fail an
    # otherwise-successful ingest.
    try:
        from aryx.cpq.data_table.data_table_resolver import (
            _clear_attr_var_mapping_cache,
            _clear_tables_cache,
        )
        from aryx.cpq.engine import (
            _clear_data_table_forced_vns_cache,
            _clear_rule_join_data_cache,
            _clear_substitute_util_get_constraint_vals_cache,
            _clear_value_rules_cache,
        )

        _clear_tables_cache()
        _clear_attr_var_mapping_cache()
        _clear_rule_join_data_cache()
        _clear_value_rules_cache()
        _clear_data_table_forced_vns_cache()
        _clear_substitute_util_get_constraint_vals_cache()
        logger.info("confirm job=%s cleared CPQ rule/table caches after ingest", job_id)
    except Exception as exc:  # noqa: BLE001 — never fail the ingest over cache invalidation
        logger.warning("confirm job=%s CPQ cache invalidation failed: %s", job_id, exc,
                       exc_info=True)

    # 2026-08-29 (PR #287 review, Section 12): the clears above only reach
    # THIS process' in-memory copy of each cache. Under multiple api
    # worker processes (P1), every OTHER worker's copy is untouched by
    # them -- this write is what lets those other workers notice, via
    # their own short-interval poll (data_table_resolver._current_
    # invalidation_marker), that a re-ingest happened somewhere and their
    # cached data may now be stale. Placed AFTER all real ingest work
    # above (plan execution, FK links, validation) has already completed
    # and committed -- a worker that sees this marker move is guaranteed
    # to see the real underlying data as of at least that point in time,
    # never a partial/in-flight ingest. Separate try/except, independent
    # of the in-process clears above: a marker-write failure must not
    # skip the in-process clear (which still protects THIS worker), and
    # vice versa.
    try:
        from aryx.store.pool import get_pool

        # Explicit short acquisition timeout -- an unreachable/exhausted
        # pool must not delay this best-effort write for psycopg_pool's
        # own 30s default; the in-process clears above already ran and
        # protect this worker regardless of whether this write succeeds.
        with get_pool(settings.effective_dsn()).connection(timeout=2.0) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE cpq_cache_invalidation_marker "
                "SET invalidated_at = NOW(), last_job_id = %s WHERE id = 1",
                (job_id,),
            )
        logger.info("confirm job=%s wrote cross-process cache invalidation marker", job_id)
    except Exception as exc:  # noqa: BLE001 — never fail the ingest over marker write
        logger.warning(
            "confirm job=%s cross-process cache invalidation marker write failed "
            "(other worker processes may serve stale CPQ data for up to the cache "
            "TTL): %s", job_id, exc, exc_info=True,
        )
