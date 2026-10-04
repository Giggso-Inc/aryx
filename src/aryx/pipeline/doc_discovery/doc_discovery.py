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
from aryx.pipeline.orchestrate import PipelineCancelled, run_pipeline
from aryx.raven_log import raven_log, submit_ctx, would_log
from aryx.worker.job_partial import note_hidden
from aryx.store.chunk_store import ChunkStore
from aryx.store.datasource_store import DatasourceStore
from aryx.store.job_store import make_should_stop
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
               workspace_id: int = 1,
               layout_items: list[tuple[bytes, str]] | None = None,
               should_stop: Callable[[], bool] | None = None) -> dict[str, Any]:
    """Read everything; return {mentions, tabular, summary} without committing.

    on_progress: optional callback forwarded to extract_mentions() for each
    document — see doc_router.DocumentRouterConnector / ontology.extract for
    the (completed, total, new_records) signature. Lets the caller persist
    partial progress on long-running (1000+ page) documents.

    workspace_id: forwarded to the cpq_ingestion raw-graph writer for XML
    files ONLY when csv_bml_enabled() is true (see the XML branch below) --
    that's the one case where this Read-stage write still has a real
    consumer (bml_graph.enrich_projection's bml_tables lookup, read back by
    csv_bml_ingestion). Otherwise unused: Confirm time re-derives and writes
    the same data from scratch regardless of anything built here.

    layout_items: CPQ layout-export files (see cpq_layout_upload_active())
    already pulled out of the caller's doc/tabular split. Surfaced here as
    plain-passthrough plans (kind="cpq_layout") in the SAME "tabular"/
    "files" summary the normal tabular flow uses, so they go through this
    screen's existing read-then-confirm UX -- nothing is written to
    aryx_cpq_layout_file until ingest_confirmed() actually approves one.

    should_stop: forwarded to the XML branch's cpq_ingestion raw-graph write
    (project_raw_graph_and_flatten -> write_raw_graph's per-chunk Oracle
    executemany loop) when csv_bml_enabled() is true -- the one case where
    that write still runs at Read time (see workspace_id above). Otherwise
    forwarded to preview_raw_graph_counts()'s count-only parse instead, so a
    cancel during a large file's ~40-78s preview is still observed. Kept
    since the caller (doc_discover_read_job.py) already builds one and the
    document-extraction path via DocumentRouterConnector/extract_mentions()
    may gain should_stop support later (a separate, still-open gap, see
    doc_discover_read_job.py's module docstring).
    """
    settings = get_settings()
    logger.info("read_files start did=%s doc_files=%d tabular_files=%d context=%r",
                did, len(doc_paths), len(tabular), context)
    mentions = []
    raven_log("DEBUG", "P4", "ingest.read.start read_files inputs",
              context={"discovery_id": did, "doc_files": len(doc_paths), "tabular_files": len(tabular),
                       "layout_files": len(layout_items or []), "has_context": bool(context),
                       "selected_option": "documents+tabular" if doc_paths and tabular else
                       ("documents" if doc_paths else "tabular"),
                       "available_options": ["documents", "tabular", "documents+tabular"],
                       "reason_code": "INPUT_MIX"})
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
    # cpq_ingestion XML files get a parse-only node/edge-count preview
    # instead of being flattened to per-tag CSVs and run through the
    # generic _infer_type loop below -- Confirm time re-parses the same
    # bytes from scratch and writes via resolve_and_relate_raw_graph()
    # regardless of anything built here (see resolve_relate.py's module
    # docstring), so neither the Oracle write project_raw_graph_and_flatten
    # used to do nor a real CSV flatten serve any purpose at Read time for
    # this pipeline -- just the counts, for the discovery-summary screen.
    cpq_preview_plans: list[dict] = []
    for d, n in tabular:
        suffix = Path(n).suffix.lower()
        raven_log("DEBUG", "P4", "ingest.read.route tabular file road chosen",
                  context={"discovery_id": did, "filename": n, "bytes": len(d),
                           "selected_option": {".xml": "xml_flatten", ".xlsx": "xlsx_flatten"}.get(suffix, "csv_consolidate"),
                           "available_options": ["xml_flatten", "xlsx_flatten", "csv_consolidate"],
                           "reason_code": "EXTENSION", "suffix": suffix})
        if suffix == ".xml":
            from aryx.cpq_ingestion.routing import cpq_ingestion_pipeline_active  # noqa: PLC0415

            if cpq_ingestion_pipeline_active(n):
                from aryx.csv_bml_ingestion.config import csv_bml_enabled  # noqa: PLC0415

                if csv_bml_enabled():
                    # csv_bml_ingestion finds scripts by searching the stored
                    # raw graph for bml_tables (see bml_graph.enrich_projection),
                    # which only gets added during project_raw_graph_and_flatten's
                    # Oracle write -- the parse-only preview below never writes
                    # anything, so an XML uploaded through this path with the
                    # flag on would leave no bml_tables for any CSV to match
                    # against. Keep the old write+flatten path alive for this
                    # one case; every other upload still gets the fast preview.
                    from aryx.cpq_ingestion.pipeline import project_raw_graph_and_flatten  # noqa: PLC0415

                    xml_csvs = project_raw_graph_and_flatten(
                        d, Path(n).stem, workspace_id=workspace_id,
                        dsn=settings.effective_dsn(), graph_url=settings.graph_url,
                        log_id=did, should_stop=should_stop,
                    )
                    for csv_bytes, csv_name in xml_csvs:
                        converted_tabular.append((csv_bytes, csv_name, n, d))
                    continue

                # Lazy import: aryx.cpq_ingestion.pipeline itself imports
                # _xml_to_csvs from this module, so a top-level import here
                # would be circular.
                from aryx.cpq_ingestion.pipeline import preview_raw_graph_counts  # noqa: PLC0415

                stem = Path(n).stem
                nodes, edges = preview_raw_graph_counts(d, stem, should_stop=should_stop)
                cpq_preview_plans.append({
                    "filename": f"{stem}.summary.csv",
                    "data": f"nodes,edges\n{nodes},{edges}\n".encode(),
                    "ontology_type": f"{nodes:,} nodes / {edges:,} edges",
                    "match_keys": [],
                    "source_filename": n,
                    "source_bytes": d,
                    # Marks this as a synthetic counts-only plan for
                    # _persist_tabular_sources: it must not be catalogued as
                    # a real generated asset (see that function's docstring).
                    "cpq_raw_graph_preview": True,
                })
                continue
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
        raven_log("DEBUG", "P4", "ingest.read.plan type and match keys inferred",
                  context={"discovery_id": did, "filename": filename, "ontology_type": inferred.get("ontology_type"),
                           "match_keys": inferred.get("match_keys"), "bytes": len(data)})
        if source_filename is not None and source_bytes is not None:
            plan["source_filename"] = source_filename
            plan["source_bytes"] = source_bytes
            try:
                headers = next(csv.reader(io.StringIO(data.decode("utf-8", "ignore"))))
            except Exception:  # noqa: BLE001
                headers = []
            if "_text" in headers:
                plan["match_keys"] = ["_text"]
            raven_log("DEBUG", "P4", "ingest.read.plan derived from parent workbook or xml",
                      context={"discovery_id": did, "filename": filename, "source_filename": source_filename,
                               "selected_option": "text_match_key" if "_text" in headers else "inferred_match_keys",
                               "available_options": ["text_match_key", "inferred_match_keys"],
                               "reason_code": "TEXT_COLUMN_PRESENT" if "_text" in headers else "NO_TEXT_COLUMN",
                               "header_column_count": len(headers)})
        elif Path(filename).suffix.lower() == ".csv":
            # A plain (not XML/XLSX-derived) CSV upload has no "parent
            # workbook" to fan back in to -- one file is already one plan --
            # so it's flagged directly here rather than routed through
            # source_filename/source_bytes, which _persist_tabular_sources()
            # (below) treats as "an XML/XLSX parent to catalog", not
            # something a plain CSV upload has.
            from aryx.cpq_ingestion.routing import cpq_ingestion_pipeline_active  # noqa: PLC0415
            if cpq_ingestion_pipeline_active(filename):
                plan["cpq_csv_direct"] = True
            raven_log("DEBUG", "P4", "ingest.read.plan csv direct-landing flag decided",
                      context={"discovery_id": did, "filename": filename,
                               "selected_option": "csv_direct" if plan.get("cpq_csv_direct") else "entity_pipeline",
                               "available_options": ["csv_direct", "entity_pipeline"],
                               "reason_code": "CPQ_INGESTION_PIPELINE_ACTIVE" if plan.get("cpq_csv_direct") else "PIPELINE_INACTIVE"})
        tab_plans.append(plan)

    tab_plans.extend(cpq_preview_plans)

    for layout_data, layout_name in (layout_items or []):
        tab_plans.append({
            "filename": layout_name, "data": layout_data,
            "ontology_type": "CPQ Layout File", "kind": "cpq_layout",
        })

    by_type: dict[str, list[str]] = {}
    for m in mentions:
        by_type.setdefault(m.payload["type"], []).append(m.payload["name"])
    types = [{"type": t, "count": len(v), "examples": list(dict.fromkeys(v))[:5]}
             for t, v in sorted(by_type.items(), key=lambda kv: -len(kv[1]))]
    files = [
        {
            "filename": p["filename"],
            "ontology_type": p["ontology_type"],
            "source_filename": p["source_filename"],
        } if p.get("source_filename") else
        {"filename": p["filename"], "ontology_type": p["ontology_type"]}
        for p in tab_plans
    ]
    logger.info("read_files done did=%s mentions=%d tabular_plans=%d types=%d files=%d",
                did, len(mentions), len(tab_plans), len(types), len(files))
    raven_log("INFO", "P4", "ingest.read.done discovery read finished",
              context={"discovery_id": did, "mentions": len(mentions), "tabular_plans": len(tab_plans),
                       "types": len(types), "files": len(files),
                       "layout_plans": len(layout_items or []), "zero_mentions": len(mentions) == 0})
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

    PR #416 review: this (the Documents-tab confirm path) built no
    should_stop at all, unlike the /admin/ingest/file path -- a job
    cancelled here while "Connecting remaining isolated entities" or any
    other run_pipeline() stage kept running server-side regardless, never
    reaching the cancellation support added to _relate_isolated/
    dimension_link. Built once and passed to every run_pipeline() call
    below (the per-mention-type loop, _run_one_plan's per-file loop, and
    -- since this gap existed here too until it was fixed -- the
    cpq_ingestion raw-graph resolve/relate loop's per-source-file and
    per-tag checks inside resolve_and_relate_raw_graph()) so all three
    observe the same cancellation state. Caller (_confirm_job) must catch
    PipelineCancelled separately -- it propagates out of run_pipeline() at
    the next stage boundary after should_stop() starts returning True.
    """
    settings = get_settings()
    datasource_store = DatasourceStore(settings.effective_dsn())
    should_stop = make_should_stop(jobs, job_id)
    total = max(len(approved_types) + len(approved_files), 1)
    step = 0
    raven_log("INFO", "P4", "ingest.confirm.start confirm plans received",
              context={"job_id": job_id, "discovery_id": discovery_id, "workspace_id": workspace_id,
                       "approved_types": len(approved_types), "approved_files": len(approved_files),
                       "resuming": bool(confirm_state), "completed_plans": len((confirm_state or {}).get("completed_plans", []))})

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
            raven_log("DEBUG", "P4", "ingest.confirm.type run chosen",
                      context={"job_id": job_id, "otype": otype, "records": len(recs), "step": step,
                               "selected_option": "relate_and_project" if is_last else "resolve_only",
                               "available_options": ["relate_and_project", "resolve_only"],
                               "reason_code": "LAST_TYPE_WITH_RECORDS" if is_last else "NOT_LAST_TYPE"})

            def _progress_otype(stage: str, pct: int, detail: str, _otype: str = otype,
                                 _step: int = step) -> None:
                jobs.update_stage(job_id, f"{_step}/{total} · {stage}",
                                  int(_step * 90 / total) + pct // 10, detail)
                logger.info("confirm job=%s otype=%s stage=%s pct=%d %s",
                            job_id, _otype, stage, pct, detail)

            run_pipeline(connector=RecordsConnector(recs, label=otype), dsn=settings.effective_dsn(),
                         system="document", dataset=otype, ontology_type=otype,
                         match_keys=["name"], graph_url=settings.graph_url, broker=broker,
                         workspace_id=workspace_id, relate=is_last, skip_graph=not is_last,
                         on_progress=_progress_otype, should_stop=should_stop)
        else:
            logger.info("confirm job=%s step=%d/%d otype=%s skipped, no matching mentions",
                        job_id, step, total, otype)
            raven_log("DEBUG", "P4", "ingest.confirm.type skipped no mentions",
                      context={"job_id": job_id, "otype": otype, "step": step, "decision": "skip",
                               "reason_code": "NO_MATCHING_MENTIONS"})

    # Collect valid plans in approval order so FK detection sees the full picture.
    # Filter out already-completed plans when resuming.
    all_valid_plans = [p for p in
                       (next((p for p in data["tabular"] if p["filename"] == fn), None)
                        for fn in approved_files)
                       if p is not None]
    valid_plans = [p for p in all_valid_plans if p["filename"] not in completed_plans]
    raven_log("DEBUG", "P4", "ingest.confirm.plans plan lists built",
              context={"job_id": job_id, "approved_files": len(approved_files), "plans_found": len(all_valid_plans),
                       "unknown_files": len(approved_files) - len(all_valid_plans),
                       "resume_skipped": len(all_valid_plans) - len(valid_plans),
                       "selected_option": "resume" if len(valid_plans) < len(all_valid_plans) else "fresh",
                       "available_options": ["resume", "fresh"], "reason_code": "COMPLETED_PLANS_IN_STATE"})
    if len(valid_plans) < len(all_valid_plans):
        logger.info("confirm job=%s resume: skipping %d completed plan(s): %s",
                    job_id, len(all_valid_plans) - len(valid_plans),
                    [p["filename"] for p in all_valid_plans if p["filename"] in completed_plans])

    # CPQ layout plans (kind="cpq_layout", see read_files()) are stored
    # verbatim via store_layout_file() here, on confirm -- never through
    # _persist_tabular_sources/FK-detection/_run_one_plan below, all of
    # which assume CSV/JSON tabular data. Removed from valid_plans up front
    # so nothing downstream ever sees one. Best-effort per file, matching
    # file_ingest_run.py's _run_files: one bad/oversized layout file is
    # logged and skipped, not allowed to fail the rest of the confirm.
    layout_plans = [p for p in valid_plans if p.get("kind") == "cpq_layout"]
    valid_plans = [p for p in valid_plans if p.get("kind") != "cpq_layout"]
    raven_log("DEBUG", "P4", "ingest.confirm.split layout plans separated",
              context={"job_id": job_id, "layout_plans": len(layout_plans), "remaining": len(valid_plans),
                       "selected_option": "store_layout" if layout_plans else "none",
                       "reason_code": "KIND_CPQ_LAYOUT"})
    if layout_plans:
        # Lazy import: aryx.cpq_ingestion.__init__ imports pipeline.py,
        # which imports _xml_to_csvs from THIS module -- a top-level import
        # here would be circular (same reasoning as the XML branch above).
        from aryx.cpq_ingestion.layout_store import CpqLayoutFileTooLarge, store_layout_file  # noqa: PLC0415
    for lp in layout_plans:
        try:
            prefix = store_layout_file(
                lp["data"], lp["filename"],
                workspace_id=workspace_id, dsn=settings.effective_dsn(),
            )
            logger.info(
                "cpq_ingestion: stored layout file via doc-discovery confirm "
                "workspace_id=%d catalog_prefix=%r filename=%r",
                workspace_id, prefix, lp["filename"],
            )
        except CpqLayoutFileTooLarge as lay_exc:
            logger.warning(
                "cpq_ingestion: layout file %s too large, skipped",
                lp["filename"], exc_info=True,
            )
            note_hidden(job_id)
            raven_log("WARN", "P3", "ingest.layout.skipped layout file too large",
                      error_code="ARYX_ING_LAYOUT_SKIPPED",
                      context={"job_id": job_id, "filename": lp["filename"], "triggering_error": type(lay_exc).__name__,
                               "reason_code": "TOO_LARGE", "attempt": 1, "max_attempts": 1, "backoff_ms": 0,
                               "recovery_selected": "skip_file", "fallback_target": None,
                               "exit_condition": "skipped", "result": "skipped"})
        except Exception as lay_exc:  # noqa: BLE001
            logger.warning(
                "cpq_ingestion: failed to store layout file %s",
                lp["filename"], exc_info=True,
            )
            note_hidden(job_id)
            raven_log("WARN", "P3", "ingest.layout.skipped layout file store failed",
                      error_code="ARYX_ING_LAYOUT_SKIPPED",
                      context={"job_id": job_id, "filename": lp["filename"], "triggering_error": type(lay_exc).__name__,
                               "reason_code": "STORE_FAILED", "attempt": 1, "max_attempts": 1, "backoff_ms": 0,
                               "recovery_selected": "skip_file", "fallback_target": None,
                               "exit_condition": "skipped", "result": "skipped"})

    # cpq_ingestion: a plain CSV upload whose plan is active for this
    # pipeline (ARYX_INGEST_FILE_TYPE includes "csv", ARYX_INGEST_PIPELINE=
    # cpq_ingestion) lands directly in Postgres (aryx_landed_record) and
    # stops there -- no resolve, no relate, no graph entity/relationship,
    # no graph projection. Excluded from `valid_plans` before
    # _persist_tabular_sources (a plain CSV upload has no "parent workbook"
    # for that function to catalog anyway -- see the cpq_csv_direct comment
    # in read_files()) and before FK detection/_run_one_plan below, for the
    # same double-resolve reasoning as the XML branch just below this one.
    from aryx.cpq_ingestion.routing import partition_cpq_ingestion_csv_plans  # noqa: PLC0415
    cpq_ingestion_csv_plans, valid_plans = partition_cpq_ingestion_csv_plans(valid_plans)
    raven_log("DEBUG", "P4", "ingest.confirm.split csv direct plans separated",
              context={"job_id": job_id, "csv_direct": len(cpq_ingestion_csv_plans), "remaining": len(valid_plans),
                       "selected_option": "csv_direct" if cpq_ingestion_csv_plans else "none",
                       "reason_code": "CPQ_CSV_DIRECT_FLAG"})

    if cpq_ingestion_csv_plans:
        from aryx.cpq_ingestion.csv_land import land_csv_directly  # noqa: PLC0415

    for plan in cpq_ingestion_csv_plans:
        filename = plan["filename"]
        stem = Path(filename).stem
        jobs.update_stage(job_id, "CPQ Ingestion", int(step * 90 / total),
                          f"Landing {filename} directly in Postgres…")
        logger.info("confirm job=%s cpq_ingestion csv_direct start filename=%s", job_id, filename)
        try:
            result = land_csv_directly(
                plan["data"], stem, workspace_id=workspace_id,
                dsn=settings.effective_dsn(), log_id=job_id,
            )
        except Exception as csv_exc:  # noqa: BLE001
            logger.warning(
                "confirm job=%s cpq_ingestion csv_direct failed filename=%s",
                job_id, filename, exc_info=True,
            )
            note_hidden(job_id)
            raven_log("WARN", "P2", "ingest.csv_direct.failed direct CSV landing failed, file skipped",
                      error_code="ARYX_ING_CSV_DIRECT_FAILED",
                      context={"job_id": job_id, "filename": filename, "triggering_error": type(csv_exc).__name__,
                               "attempt": 1, "max_attempts": 1, "backoff_ms": 0, "recovery_selected": "skip_file",
                               "fallback_target": None, "exit_condition": "skipped", "result": "skipped",
                               "failed_files": [filename]})
            continue
        logger.info("confirm job=%s cpq_ingestion csv_direct done filename=%s result=%s",
                    job_id, filename, result)
        raven_log("DEBUG", "P4", "ingest.confirm.csv_direct landed",
                  context={"job_id": job_id, "filename": filename, "rows_landed": result.get("rows_landed"),
                           "run_id": result.get("run_id")})

    _persist_tabular_sources(valid_plans, workspace_id, settings.effective_dsn())

    # cpq_ingestion: an XML file whose plans are still active for this
    # pipeline (ARYX_INGEST_FILE_TYPE/ARYX_INGEST_PIPELINE) gets resolved and
    # related directly from its raw graph instead of through the generic CSV
    # pipeline below -- see partition_cpq_ingestion_plans()'s docstring for
    # why this groups by source_filename rather than iterating plans
    # directly. Excluded from `valid_plans` before FK detection and
    # `_run_one_plan` below for the same reason: these records already went
    # through containment-based relate, not FK-guessing, so re-running them
    # through the CSV path would both double-resolve them and pollute FK
    # detection with columns (`_text`, entity tag names) that were never
    # meant to be joined on.
    from aryx.cpq_ingestion.routing import partition_cpq_ingestion_plans  # noqa: PLC0415
    cpq_ingestion_source_files, valid_plans = partition_cpq_ingestion_plans(valid_plans)
    raven_log("DEBUG", "P4", "ingest.confirm.split xml raw-graph plans separated",
              context={"job_id": job_id, "xml_source_files": len(cpq_ingestion_source_files),
                       "remaining": len(valid_plans),
                       "selected_option": "raw_graph_resolve" if cpq_ingestion_source_files else "none",
                       "reason_code": "CPQ_XML_ACTIVE"})

    for source_filename, plan in cpq_ingestion_source_files.items():
        # Mirrors _run_one_plan's own top-of-iteration should_stop check below --
        # a job cancelled while a PREVIOUS source file's resolve/relate was still
        # running, or between files, must not start the next ~100+-minute file.
        if should_stop():
            raise PipelineCancelled(f"job cancelled before source_filename={source_filename}")
        from aryx.cpq_ingestion.raw_graph.resolve_relate import resolve_and_relate_raw_graph  # noqa: PLC0415

        step += 1
        stem = Path(source_filename).stem
        jobs.update_stage(job_id, f"{step}/{total} · CPQ Ingestion", int(step * 90 / total),
                          f"Resolving {source_filename} directly from its raw graph…")
        logger.info("confirm job=%s cpq_ingestion resolve/relate start source_filename=%s",
                    job_id, source_filename)

        def _progress_cpq(stage: str, pct: int, detail: str,
                           _fname: str = source_filename, _step: int = step) -> None:
            # Same convention as _progress_otype/_progress_plan: this file's
            # own 0-100 progress contributes up to 10 points within its step
            # band so the overall job pct still advances smoothly across
            # files, not just within one.
            jobs.update_stage(job_id, f"{_step}/{total} · CPQ Ingestion · {stage}",
                              int(_step * 90 / total) + pct // 10, detail)
            logger.info("confirm job=%s cpq_ingestion source_filename=%s stage=%s pct=%d %s",
                        job_id, _fname, stage, pct, detail)

        # §3b (2026-10-04): passing xml_bytes directly lets
        # resolve_and_relate_raw_graph() itself decide eager vs. streaming
        # (ARYX_CPQ_STREAMING_PROJECTION_ENABLED, default off) -- this call
        # site no longer needs to know which path is active.
        result = resolve_and_relate_raw_graph(
            xml_bytes=plan["source_bytes"], workspace_id=workspace_id, source_key=stem,
            dsn=settings.effective_dsn(), graph_url=settings.graph_url,
            broker=broker, log_id=job_id, should_stop=should_stop,
            on_progress=_progress_cpq,
        )
        logger.info("confirm job=%s cpq_ingestion resolve/relate done source_filename=%s result=%s",
                    job_id, source_filename, result)

    def _report_fk_stage(pct: int, detail: str) -> None:
        # A transient job-store failure while reporting progress must never
        # abort real FK-detection work — same discipline as dynamic_fk.py's
        # own on_progress guard (judge_candidates_with_llm).
        try:
            jobs.update_stage(job_id, "FK Detection", pct, detail)
        except Exception as stage_exc:  # noqa: BLE001
            logger.warning("confirm job=%s FK-detection stage report failed", job_id, exc_info=True)
            raven_log("DEBUG", "P4", "ingest.confirm.fk_stage progress report failed, detection continues",
                      context={"job_id": job_id, "pct": pct, "error_class": type(stage_exc).__name__,
                               "recovery_selected": "continue", "result": "degraded"})

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
    raven_log("DEBUG", "P4", "ingest.confirm.fk column-name pass finished",
              context={"job_id": job_id, "plans": len(valid_plans), "fk_links": len(auto_fk),
                       "selected_option": "links_found" if auto_fk else "no_links",
                       "reason_code": "COLUMN_NAME_FK"})

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
        raven_log("DEBUG", "P4", "ingest.confirm.fk script data-flow links added",
                  context={"job_id": job_id, "links": len(script_flow_links)})

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
            raven_log("WARN", "P3", "ingest.confirm.workspace_fk skipped, ontology lookup failed",
                      error_code="ARYX_ING_WORKSPACE_FK_SKIPPED",
                      context={"job_id": job_id, "triggering_error": type(exc).__name__, "attempt": 1,
                               "max_attempts": 1, "backoff_ms": 0, "recovery_selected": "skip_workspace_fk",
                               "fallback_target": None, "exit_condition": "skipped", "result": "degraded"})
        existing_pairs: set[tuple[str, str]] = {
            (lk["source_type"], lk["target_type"]) for lk in auto_fk
        }
        workspace_fk = _detect_fk_links_workspace(
            valid_plans[-1], known_types, seen=existing_pairs, job_id=job_id
        )
        raven_log("DEBUG", "P4", "ingest.confirm.fk workspace pass finished",
                  context={"job_id": job_id, "known_types": len(known_types), "workspace_links": len(workspace_fk),
                           "selected_option": "links_found" if workspace_fk else "no_links",
                           "reason_code": "WORKSPACE_LEVEL_FK"})
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
        raven_log("DEBUG", "P4", "ingest.confirm.fk dynamic pass finished",
                  context={"job_id": job_id, "dynamic_links": len(dynamic_fk), "already_linked_pairs": len(already_linked),
                           "selected_option": "links_found" if dynamic_fk else "no_links",
                           "reason_code": "VALUE_OVERLAP_LLM_JUDGE"})
        if dynamic_fk:
            auto_fk.extend(dynamic_fk)
            logger.info("confirm job=%s dynamic (value+LLM) fk-link spec(s): %d: %s",
                        job_id, len(dynamic_fk), dynamic_fk)

    def _run_one_plan(plan: dict, is_last: bool, plan_step: int) -> None:
        """Run a single tabular plan through the pipeline.

        PR #416 review: run_pipeline()'s own should_stop checks don't start
        until its "relate" stage boundary -- discover and resolve_cluster
        run unconditionally before that. For a queued (not yet started)
        non-last plan picked up by a worker thread after the job was already
        cancelled, that meant the whole discover+resolve pass still ran and
        landed records for a plan nobody wanted anymore. Checking here, at
        the very top, means a plan that hasn't started yet bails immediately
        instead of doing any of that work.
        """
        if should_stop():
            raise PipelineCancelled(f"job cancelled before plan={plan['filename']}")
        fname = plan["filename"]
        otype = plan["ontology_type"]
        logger.info("confirm job=%s step=%d/%d file=%s otype=%s is_last=%s",
                    job_id, plan_step, total, fname, otype, is_last)
        plan_t0 = time.perf_counter()
        raven_log("DEBUG", "P4", "ingest.confirm.plan start",
                  context={"job_id": job_id, "filename": fname, "otype": otype, "plan_step": plan_step,
                           "bytes": len(plan["data"]), "match_keys": plan.get("match_keys"),
                           "selected_option": "relate_and_project" if is_last else "resolve_only",
                           "available_options": ["relate_and_project", "resolve_only"],
                           "reason_code": "LAST_PLAN" if is_last else "NOT_LAST_PLAN",
                           "relate": is_last and settings.ingest_relate, "skip_graph": not is_last,
                           "fk_links": len(auto_fk) if is_last else 0})
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
            run_pipeline(connector=conn, dsn=settings.effective_dsn(),
                         system=Path(fname).suffix.lstrip("."), dataset=Path(fname).stem,
                         ontology_type=otype, match_keys=plan["match_keys"],
                         graph_url=settings.graph_url, broker=broker, workspace_id=workspace_id,
                         fk_links=auto_fk if is_last else None,
                         relate=is_last and settings.ingest_relate,
                         skip_graph=not is_last,
                         on_progress=_progress_plan, should_stop=should_stop)
            suffix = Path(fname).suffix.lower()
            if suffix in {".csv", ".json"}:
                restore_generic_source_entry(
                    datasource_store,
                    workspace_id=workspace_id,
                    source_system=suffix.lstrip("."),
                    source_dataset=Path(fname).stem,
                )
            logger.info("confirm job=%s file=%s done", job_id, fname)
            raven_log("DEBUG", "P4", "ingest.confirm.plan done",
                      context={"job_id": job_id, "filename": fname,
                               "duration_ms": int((time.perf_counter() - plan_t0) * 1000),
                               "persist_state": bool(discovery_id)})
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
        raven_log("DEBUG", "P4", "ingest.confirm.parallel non-last plans run in parallel",
                  context={"job_id": job_id, "non_last_plans": len(non_last), "workers": settings.ingest_workers,
                           "selected_option": "parallel_then_last", "available_options": ["parallel_then_last", "last_only"],
                           "reason_code": "NON_LAST_PLANS_PRESENT"})
        with ThreadPoolExecutor(max_workers=settings.ingest_workers) as pool:
            futs = {submit_ctx(pool, _run_one_plan, p, False, plan_steps[p["filename"]]): p["filename"]
                    for p in non_last}
            failed: list[str] = []
            for fut in as_completed(futs):
                fname_done = futs[fut]
                try:
                    fut.result()
                    logger.info("confirm job=%s plan complete file=%s", job_id, fname_done)
                except PipelineCancelled:
                    # PR #416 review: previously caught by the bare `except
                    # Exception` below, logged as "plan failed" with a full
                    # stack trace, and the loop just continued on to the next
                    # plan -- a cancel was indistinguishable from a genuine
                    # failure, and every other queued plan still ran to
                    # completion before this function returned. cancel_futures
                    # abandons any not-yet-started plan immediately (an
                    # already-running one still bails fast via the should_stop
                    # check _run_one_plan now does at its own top); re-raising
                    # propagates PipelineCancelled up to _confirm_job the same
                    # way the serial "last" plan's cancellation already did.
                    logger.info("confirm job=%s plan cancelled file=%s — abandoning queued plans",
                               job_id, fname_done)
                    raven_log("INFO", "P3", "ingest.confirm.plan_cancelled queued plans abandoned",
                              context={"job_id": job_id, "object_id": job_id, "filename": fname_done,
                                       "previous_state": "running", "requested_state": "cancelled",
                                       "final_state": "cancelled", "trigger": "should_stop",
                                       "result": "abandoned_queued", "reason_code": "USER_CANCEL",
                                       "plans_total": len(valid_plans)})
                    pool.shutdown(wait=False, cancel_futures=True)
                    raise
                except Exception as plan_exc:
                    logger.warning("confirm job=%s plan failed file=%s",
                                   job_id, fname_done, exc_info=True)
                    failed.append(fname_done)
                    raven_log("DEBUG", "P4", "ingest.confirm.plan failed",
                              context={"job_id": job_id, "filename": fname_done,
                                       "error_class": type(plan_exc).__name__})
            if failed:
                logger.warning(
                    "confirm job=%s skipping %d failed plan(s): %s — continuing with remaining",
                    job_id, len(failed), failed,
                )
                note_hidden(job_id)
                raven_log("WARN", "P2", "ingest.confirm.plans_failed some plans failed, job continues",
                          error_code="ARYX_ING_PLAN_FAILED",
                          context={"job_id": job_id, "triggering_error": "plan_exception", "attempt": 1,
                                   "max_attempts": 1, "backoff_ms": 0, "recovery_selected": "skip_failed_plans",
                                   "fallback_target": None, "exit_condition": "continue_with_remaining",
                                   "result": "partial", "failed_count": len(failed), "failed_files": failed[:20],
                                   "plans_total": len(valid_plans)})

    raven_log("DEBUG", "P4", "ingest.confirm.last_plan decision",
              context={"job_id": job_id, "selected_option": "run_last" if last else "no_last_plan",
                       "available_options": ["run_last", "no_last_plan"],
                       "reason_code": "VALID_PLANS_PRESENT" if last else "NO_VALID_PLANS",
                       "valid_plans": len(valid_plans)})
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
            failure_lines = list(report.failures())
            for line in failure_lines:
                logger.warning("confirm job=%s validation FAIL %s", job_id, line)
            if failure_lines or not report.passed:
                note_hidden(job_id)
                raven_log("WARN", "P2", "ingest.validation.failed zero-loss validation found problems",
                          error_code="ARYX_ING_VALIDATION_FAILED",
                          context={"job_id": job_id, "final_status": "complete", "stage": "validation",
                                   "result": "failed", "reason_code": "CHECKS_FAILED",
                                   "checks_failed": len(failure_lines), "passed": bool(report.passed),
                                   "impact_scope": {"plans": len(valid_plans)}})
            else:
                raven_log("DEBUG", "P4", "ingest.validation.passed zero-loss validation clean",
                          context={"job_id": job_id, "stage": "validation", "result": "ok", "passed": True,
                                   "plans": len(valid_plans)})
        except Exception as exc:  # noqa: BLE001 — never fail the ingest over validation
            logger.warning("confirm job=%s validation crashed: %s", job_id, exc,
                           exc_info=True)
            note_hidden(job_id)
            raven_log("WARN", "P2", "ingest.validation.failed validation crashed",
                      error_code="ARYX_ING_VALIDATION_FAILED",
                      context={"job_id": job_id, "final_status": "complete", "stage": "validation",
                               "result": "error", "reason_code": "VALIDATION_CRASHED",
                               "error_class": type(exc).__name__})
    else:
        raven_log("DEBUG", "P4", "ingest.validation.skipped no plans to validate",
                  context={"job_id": job_id, "selected_option": "skip", "available_options": ["run", "skip"],
                           "reason_code": "NO_VALID_PLANS"})

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
        raven_log("DEBUG", "P4", "ingest.cache_invalidate in-process CPQ caches cleared",
                  context={"job_id": job_id, "caches_cleared": 6, "result": "ok"})
    except Exception as exc:  # noqa: BLE001 — never fail the ingest over cache invalidation
        logger.warning("confirm job=%s CPQ cache invalidation failed: %s", job_id, exc,
                       exc_info=True)
        note_hidden(job_id)
        raven_log("WARN", "P2", "ingest.cache_invalidate.failed in-process CPQ cache clear failed",
                  error_code="ARYX_ING_CACHE_INVALIDATE_FAILED",
                  context={"job_id": job_id, "dependency_name": "cpq_cache", "operation": "clear_in_process",
                           "result": "error", "error_class": type(exc).__name__, "attempt": 1,
                           "stale_risk_ttl_s": 300})

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
        raven_log("DEBUG", "P4", "ingest.cache_invalidate marker written",
                  context={"job_id": job_id, "dependency_name": "adb", "operation": "write_marker", "result": "ok"})
    except Exception as exc:  # noqa: BLE001 — never fail the ingest over marker write
        logger.warning(
            "confirm job=%s cross-process cache invalidation marker write failed "
            "(other worker processes may serve stale CPQ data for up to the cache "
            "TTL): %s", job_id, exc, exc_info=True,
        )
        note_hidden(job_id)
        raven_log("WARN", "P2", "ingest.cache_invalidate.failed cross-process marker write failed",
                  error_code="ARYX_ING_CACHE_INVALIDATE_FAILED",
                  context={"job_id": job_id, "dependency_name": "adb", "operation": "write_marker",
                           "result": "error", "error_class": type(exc).__name__, "attempt": 1,
                           "stale_risk_ttl_s": 300})
