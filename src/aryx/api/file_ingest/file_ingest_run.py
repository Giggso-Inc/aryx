"""Background ingest worker: runs the pipeline for one uploaded file batch.

Split out of `api/file_ingest_api.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). `_run_files` is the function submitted to the ingest executor by
`file_ingest_api.file_ingest_router()`'s POST handler.
"""
from __future__ import annotations

import csv as _csv
import io
import itertools
import logging
import time
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile

from aryx.api.admin_api import _local_broker
from aryx.api.file_ingest.file_ingest_limits import _DATA_EXTS, _DOC_EXTS
from aryx.config import get_settings
from aryx.connectors.csv_source import CsvConnector
from aryx.connectors.doc_router import DocumentRouterConnector
from aryx.connectors.json_source import JsonConnector
from aryx.cpq_ingestion.pipeline import project_raw_graph_and_flatten
from aryx.cpq_ingestion.routing import cpq_ingestion_pipeline_active
from aryx.csv_bml_ingestion.config import csv_bml_enabled
from aryx.pipeline.doc_discovery.doc_discovery import _detect_fk_links, _stem_type, _xlsx_to_csvs, _xml_to_csvs
from aryx.pipeline.dynamic_fk.dynamic_fk import detect_dynamic_fk_links
from aryx.pipeline.orchestrate import PipelineCancelled, run_pipeline
from aryx.store.chunk_store import ChunkStore
from aryx.store.datasource_store import DatasourceStore
from aryx.store.job_store import JobStore
from aryx.source.source_catalog import (
    restore_generic_source_entry,
    upsert_xlsx_catalog_entry,
    upsert_xml_catalog_entry,
    xlsx_asset_record,
    xml_asset_record,
)

logger = logging.getLogger(__name__)


def _save_tmp(data: bytes, suffix: str) -> Path:
    tmp = NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(data)
    tmp.close()
    return Path(tmp.name)


def _chunk_csv_bytes(data: bytes, chunk_rows: int) -> list[bytes]:
    """Split CSV bytes into chunks of at most chunk_rows data rows, repeating the header.

    Streams rows via itertools.islice so the full file is never materialised
    into a list — only one batch is held in memory at a time.
    """
    reader = _csv.reader(io.StringIO(data.decode("utf-8")))
    try:
        header = next(reader)
    except StopIteration:
        return [data]
    chunks: list[bytes] = []
    while True:
        batch = list(itertools.islice(reader, chunk_rows))
        if not batch:
            break
        buf = io.StringIO()
        writer = _csv.writer(buf)
        writer.writerow(header)
        writer.writerows(batch)
        chunks.append(buf.getvalue().encode("utf-8"))
    return chunks or [data]


def _make_should_stop(jobs: JobStore, job_id: str, min_interval_s: float = 1.0) -> Callable[[], bool]:
    """Cheap, throttled cancellation check for a running job's worker thread.

    POST /admin/jobs/{job_id}/cancel only ever updated the job-store row
    (see jobs_api.py) -- nothing in the pipeline ever read it back, so a
    "cancelled" job kept running to completion regardless, consuming a
    worker-pool slot the whole time (confirmed live: 20+ minutes of entity
    creation after cancellation). This closure is polled from inside the
    pipeline's hottest loops (dimension_link.py) and at each stage boundary
    (orchestrate.py) -- real DB reads are throttled to at most once per
    `min_interval_s` regardless of how often the caller checks, so callers
    can poll every iteration without hammering Postgres.
    """
    state = {"last_check": 0.0, "cancelled": False}

    def should_stop() -> bool:
        if state["cancelled"]:
            return True
        now = time.monotonic()
        if now - state["last_check"] < min_interval_s:
            return False
        state["last_check"] = now
        row = jobs.get(job_id)
        if row is not None and row.get("status") == "cancelled":
            state["cancelled"] = True
        return state["cancelled"]

    return should_stop


def _run_files(items: list[tuple[bytes, str]], ontology_type: str,
               match_keys: list[str], fk_links: list[dict], job_id: str,
               workspace_id: int = 1) -> None:
    """Run the ingest pipeline for a batch of files in a background thread."""
    settings = get_settings()
    jobs: JobStore | None = None
    tmp_paths: list[Path] = []
    datasource_store = DatasourceStore(settings.effective_dsn())
    try:
        jobs = JobStore(settings.effective_dsn())
        # Register each uploaded file as a datasource so the workspace card shows
        # an accurate file count regardless of whether files were ingested via the
        # file upload page or through the Shay datasource flow.
        ds_store = DatasourceStore(settings.effective_dsn())
        for _, fname in items:
            kind = "docs" if Path(fname).suffix.lower() in _DOC_EXTS else "csv"
            try:
                ds_store.ensure(workspace_id, fname[:255], kind)
            except Exception as ds_exc:
                logger.warning("datasource ensure failed for %s: %s", fname, ds_exc)
        on_prog = lambda s, p, d: jobs.update_stage(job_id, s, p, d)
        should_stop = _make_should_stop(jobs, job_id)
        broker = _local_broker()
        data_files = [(d, n) for d, n in items if Path(n).suffix.lower() in _DATA_EXTS]
        doc_files = [(d, n) for d, n in items if Path(n).suffix.lower() in _DOC_EXTS]

        # Pre-compute FK links for multi-file CSV uploads so that cross-file
        # relationships are detected before any pipeline runs (mirrors XML path).
        csv_data_files = [(d, n) for d, n in data_files if Path(n).suffix.lower() == ".csv"]
        csv_auto_fk: list[dict] = []
        csv_type_map: dict[str, str] = {}  # filename -> derived ontology type
        if len(csv_data_files) > 1:
            csv_plans = []
            for csv_d, csv_n in csv_data_files:
                derived = _stem_type(csv_n) or ontology_type
                csv_type_map[csv_n] = derived
                csv_plans.append({
                    "data": csv_d,
                    "filename": csv_n,
                    "ontology_type": derived,
                    "match_keys": match_keys or ["name"],
                })
            csv_auto_fk = _detect_fk_links(csv_plans)
            if csv_auto_fk:
                logger.info(
                    "CSV multi-file: auto-detected %d fk-link spec(s): %s",
                    len(csv_auto_fk), csv_auto_fk,
                )

        # Pre-compute FK links for ALL xlsx workbooks in this batch TOGETHER,
        # not per-workbook. Detecting FK links inside the per-file loop below
        # (as used to happen here) means each workbook's sheets are only ever
        # compared against sheets of the SAME workbook — a relationship
        # between EBS LSN List.xlsx and DLA DS SCRAP FY25.xlsx, say, could
        # never be found regardless of column names or upload order, because
        # the two workbooks are never in the same _detect_fk_links() call.
        # Expanding every xlsx file's sheets into one pool first — exactly
        # mirroring the csv_data_files pattern above — fixes that structurally.
        xlsx_data_files = [(d, n) for d, n in data_files if Path(n).suffix.lower() == ".xlsx"]
        xlsx_all_plans: list[dict] = []  # one dict per worksheet, across ALL xlsx files
        xlsx_plans_by_file: dict[str, list[dict]] = {}
        if xlsx_data_files:
            for xlsx_d, xlsx_n in xlsx_data_files:
                orig_stem = Path(xlsx_n).stem
                xlsx_csvs = _xlsx_to_csvs(xlsx_d, orig_stem)
                if not xlsx_csvs:
                    logger.info("xlsx upload %r produced no ingestible sheets "
                               "(all hidden/empty)", xlsx_n)
                    xlsx_plans_by_file[xlsx_n] = []
                    continue
                file_plans = []
                prefix = orig_stem + "__"
                for csv_data, csv_name in xlsx_csvs:
                    csv_stem = Path(csv_name).stem
                    sheet_slug = csv_stem[len(prefix):] if csv_stem.startswith(prefix) else csv_stem
                    derived_type = _stem_type(sheet_slug) or ontology_type
                    plan = {
                        "data": csv_data, "filename": csv_name,
                        "ontology_type": derived_type,
                        "match_keys": match_keys or ["name"],
                    }
                    file_plans.append(plan)
                    xlsx_all_plans.append(plan)
                xlsx_plans_by_file[xlsx_n] = file_plans
            xlsx_auto_fk = _detect_fk_links(xlsx_all_plans, log_id=job_id)
            if xlsx_auto_fk:
                logger.info(
                    "XLSX multi-workbook: auto-detected %d column-name fk-link spec(s): %s",
                    len(xlsx_auto_fk), xlsx_auto_fk,
                )
            already_linked = {(lk["source_type"], lk["target_type"]) for lk in xlsx_auto_fk}
            xlsx_dynamic_fk = detect_dynamic_fk_links(
                xlsx_all_plans, broker, already_linked=already_linked, log_id=job_id,
            )
            if xlsx_dynamic_fk:
                xlsx_auto_fk.extend(xlsx_dynamic_fk)
                logger.info(
                    "XLSX multi-workbook: dynamic (value+LLM) fk-link spec(s): %d: %s",
                    len(xlsx_dynamic_fk), xlsx_dynamic_fk,
                )
        else:
            xlsx_auto_fk = []

        csv_bml_problems: list[str] = []
        bml_session = None
        if csv_bml_enabled():
            # XML first, so its knowledge graph exists before any CSV in the same upload looks for it
            data_files = sorted(data_files, key=lambda f: Path(f[1]).suffix.lower() != ".xml")
        for data, name in data_files:
            suffix = Path(name).suffix.lower()
            if suffix == ".json":
                tmp = _save_tmp(data, ".json")
                tmp_paths.append(tmp)
                jobs.update_stage(job_id, "Ingest", 20, f"Processing {name}")
                run_pipeline(
                    connector=JsonConnector(tmp, system="json"),
                    dsn=settings.effective_dsn(),
                    system="json", dataset=Path(name).stem,
                    ontology_type=ontology_type, match_keys=match_keys,
                    graph_url=settings.graph_url, broker=broker,
                    on_progress=on_prog, should_stop=should_stop,
                    fk_links=fk_links, workspace_id=workspace_id,
                    relate=True,
                )
                restore_generic_source_entry(
                    datasource_store,
                    workspace_id=workspace_id,
                    source_system="json",
                    source_dataset=Path(name).stem,
                )
            elif suffix == ".xml":
                # Expand XML into one connector per top-3 element type.
                # Each CSV gets its own ontology_type derived from the element
                # tag so that cross-type pairs are generated for relate/fk_link.
                orig_stem = Path(name).stem
                if cpq_ingestion_pipeline_active(name):
                    xml_csvs = project_raw_graph_and_flatten(
                        data, orig_stem, workspace_id=workspace_id,
                        dsn=settings.effective_dsn(), graph_url=settings.graph_url,
                    )
                else:
                    xml_csvs = _xml_to_csvs(data, orig_stem)
                xml_plans = []
                for csv_data, csv_name in xml_csvs:
                    csv_stem = Path(csv_name).stem
                    # csv_name == "{orig_stem}_{tag}.csv" — strip the prefix to get the tag.
                    tag = csv_stem[len(orig_stem) + 1:] if csv_stem.startswith(orig_stem + "_") else csv_stem
                    derived_type = "".join(w.title() for w in tag.split("_") if w) or ontology_type
                    xml_plans.append((csv_data, csv_name, derived_type))
                # Auto-detect FK links now that all element types are known.
                fk_plan_dicts = [
                    {"data": d, "filename": n, "ontology_type": t, "match_keys": match_keys or ["name"]}
                    for d, n, t in xml_plans
                ]
                auto_fk = _detect_fk_links(fk_plan_dicts)
                if auto_fk:
                    logger.info("XML auto-detected %d fk-link spec(s): %s", len(auto_fk), auto_fk)
                for idx, (csv_data, csv_name, derived_type) in enumerate(xml_plans):
                    is_last = (idx == len(xml_plans) - 1)
                    jobs.update_stage(job_id, "Ingest", 20, f"Processing {csv_name}")
                    # relate/skip_graph mirror ingest_confirmed() semantics:
                    # - relate only on the last plan (full entity set visible)
                    # - skip_graph on all but the last (project_graph clears+rebuilds the
                    #   entire workspace graph; N rebuilds for N plans wastes wall-clock
                    #   and causes the UI to flash with partial graphs mid-ingest)
                    run_pipeline(
                        connector=CsvConnector(csv_data, system="csv",
                                               dataset=Path(csv_name).stem),
                        dsn=settings.effective_dsn(),
                        system="csv", dataset=Path(csv_name).stem,
                        ontology_type=derived_type, match_keys=match_keys,
                        graph_url=settings.graph_url, broker=broker,
                        on_progress=on_prog, should_stop=should_stop,
                        fk_links=auto_fk if is_last else [],
                        workspace_id=workspace_id,
                        relate=is_last,
                        skip_graph=not is_last,
                    )
                asset_rows = [
                    xml_asset_record(
                        filename=csv_name,
                        dataset=Path(csv_name).stem,
                        ontology_type=derived_type,
                        content_bytes=csv_data,
                    )
                    for csv_data, csv_name, derived_type in xml_plans
                ]
                upsert_xml_catalog_entry(
                    datasource_store,
                    workspace_id=workspace_id,
                    source_filename=name,
                    xml_bytes=data,
                    assets=asset_rows,
                )
                continue
            elif suffix == ".csv" and csv_bml_enabled():
                # CSV -> table named after the file, only if a query for that table exists in the
                # XML knowledge graph already ingested into this workspace (csv_bml_ingestion).
                from aryx.csv_bml_ingestion.upload_hook import CsvBmlUploadSession

                bml_session = bml_session or CsvBmlUploadSession(workspace_id)
                jobs.update_stage(job_id, "Ingest", 20, f"Processing {name} (csv_bml_ingestion)")
                bml_res = bml_session.ingest(data, name)
                jobs.update_stage(job_id, "Ingest", 20,
                                  f"{name}: {bml_res.status} rows={bml_res.rows_loaded} {bml_res.error_code}".strip())
                if bml_res.status != "loaded":
                    csv_bml_problems.append(f"{name}: {bml_res.status} {bml_res.error_code} {bml_res.message}"[:300])
            elif suffix == ".xlsx":
                # Sheets + FK links (column-name AND dynamic value+LLM) were
                # already computed ONCE across ALL xlsx files in this batch,
                # above — see xlsx_all_plans/xlsx_auto_fk. is_last is computed
                # against that GLOBAL sheet list, not this file's own sheets,
                # so relate/graph-projection only fire once for the whole
                # batch (mirrors the XML path's is_last/skip_graph pattern).
                file_plans = xlsx_plans_by_file.get(name, [])
                if not file_plans:
                    continue
                global_last_plan = xlsx_all_plans[-1] if xlsx_all_plans else None
                for plan in file_plans:
                    csv_data, csv_name, derived_type = plan["data"], plan["filename"], plan["ontology_type"]
                    is_last = plan is global_last_plan
                    jobs.update_stage(job_id, "Ingest", 20, f"Processing {csv_name}")
                    run_pipeline(
                        connector=CsvConnector(csv_data, system="csv",
                                               dataset=Path(csv_name).stem),
                        dsn=settings.effective_dsn(),
                        system="csv", dataset=Path(csv_name).stem,
                        ontology_type=derived_type, match_keys=match_keys,
                        graph_url=settings.graph_url, broker=broker,
                        on_progress=on_prog, should_stop=should_stop,
                        fk_links=xlsx_auto_fk if is_last else [],
                        workspace_id=workspace_id,
                        relate=is_last,
                        skip_graph=not is_last,
                    )
                asset_rows = [
                    xlsx_asset_record(
                        filename=plan["filename"],
                        dataset=Path(plan["filename"]).stem,
                        ontology_type=plan["ontology_type"],
                        content_bytes=plan["data"],
                    )
                    for plan in file_plans
                ]
                upsert_xlsx_catalog_entry(
                    datasource_store,
                    workspace_id=workspace_id,
                    source_filename=name,
                    xlsx_bytes=data,
                    assets=asset_rows,
                )
                continue
            else:
                # Multi-file CSV: derive type per filename and apply auto FK links
                # on the last file's last chunk (same pattern as XML sub-pipeline).
                # Single-file CSV: preserve user-provided ontology_type and fk_links.
                multi_csv = len(csv_data_files) > 1
                is_last_csv = multi_csv and (name == csv_data_files[-1][1])
                eff_type = csv_type_map.get(name, ontology_type) if multi_csv else ontology_type
                eff_fk = csv_auto_fk if is_last_csv else (fk_links if not multi_csv else [])
                eff_relate = is_last_csv if multi_csv else settings.ingest_relate

                chunk_rows = settings.csv_chunk_rows
                csv_chunks = _chunk_csv_bytes(data, chunk_rows) if chunk_rows > 0 else [data]
                stem = Path(name).stem
                total_chunks = len(csv_chunks)
                for chunk_idx, chunk_data in enumerate(csv_chunks):
                    is_last_chunk = (chunk_idx == total_chunks - 1)
                    dataset = f"{stem}_c{chunk_idx:04d}" if total_chunks > 1 else stem
                    jobs.update_stage(
                        job_id, "Ingest", 20,
                        f"Processing {name}" + (f" chunk {chunk_idx + 1}/{total_chunks}" if total_chunks > 1 else ""),
                    )
                    run_pipeline(
                        connector=CsvConnector(chunk_data, system="csv", dataset=dataset),
                        dsn=settings.effective_dsn(),
                        system="csv", dataset=dataset,
                        ontology_type=eff_type, match_keys=match_keys,
                        graph_url=settings.graph_url, broker=broker,
                        on_progress=on_prog, should_stop=should_stop,
                        fk_links=eff_fk if is_last_chunk else [],
                        workspace_id=workspace_id,
                        relate=eff_relate and is_last_chunk,
                        skip_graph=not is_last_chunk,
                    )
                restore_generic_source_entry(
                    datasource_store,
                    workspace_id=workspace_id,
                    source_system="csv",
                    source_dataset=stem,
                )
        if doc_files:
            jobs.update_stage(job_id, "Documents", 50, f"Chunking {len(doc_files)} doc(s)")
            doc_paths = [_save_tmp(d, Path(n).suffix) for d, n in doc_files]
            tmp_paths.extend(doc_paths)
            chunk_store = ChunkStore(settings.effective_dsn())
            connector = DocumentRouterConnector(
                paths=doc_paths, system="document", broker=broker,
                chunk_store=chunk_store, chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap, expected_embed_dim=settings.embed_dim,
            )
            run_pipeline(
                connector=connector, dsn=settings.effective_dsn(),
                system="document", dataset="upload",
                ontology_type=ontology_type, match_keys=match_keys,
                graph_url=settings.graph_url, broker=broker,
                on_progress=on_prog, should_stop=should_stop,
                fk_links=fk_links, workspace_id=workspace_id,
                relate=True,
            )
        if csv_bml_problems:
            jobs.finish(job_id, run_id=None, status="failed", error="; ".join(csv_bml_problems)[:2000])
        else:
            jobs.finish(job_id, run_id=None, status="complete")
    except PipelineCancelled:
        # The job row is already "cancelled" (that's what should_stop() just
        # read to get here) -- leave it alone, don't overwrite it with
        # "failed". This is the actual fix: the worker thread now really
        # stops instead of running the rest of the pipeline to completion.
        logger.info("file ingest cancelled job=%s", job_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("file ingest failed job=%s: %s", job_id, exc)
        if jobs is not None:
            jobs.finish(job_id, run_id=None, status="failed", error=str(exc))
    finally:
        if jobs is not None:
            jobs.close()
        for p in tmp_paths:
            p.unlink(missing_ok=True)
