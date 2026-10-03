"""Per-file connector routing for the OCI Functions ingest handler.

Split out of `worker/fn_handler.py` (Raven Style Compliance Plan, Phase
2b, 2026-09-03). Zero test patches against this module (this file has no
importers/tests at all — confirmed via grep) — the split was purely
mechanical.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from aryx.raven_log import raven_log, would_log

logger = logging.getLogger(__name__)

_DOC_EXTS = {
    ".pdf", ".pptx", ".ppt", ".docx", ".doc", ".rtf",
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp",
}


def _dispatch(
    suffix: str,
    file_bytes: bytes,
    filename: str,
    settings: Any,
    broker: Any,
    on_progress: Any,
    ontology_type: str,
    match_keys: list,
    fk_links: list,
    workspace_id: int,
) -> None:
    """Route one file to the correct connector and run the full ingest pipeline."""
    from aryx.connectors.csv_source import CsvConnector  # noqa: PLC0415
    from aryx.connectors.doc_router import DocumentRouterConnector  # noqa: PLC0415
    from aryx.connectors.json_source import JsonConnector  # noqa: PLC0415
    from aryx.pipeline.orchestrate import run_pipeline  # noqa: PLC0415
    from aryx.store.chunk_store import ChunkStore  # noqa: PLC0415

    tmp_path: Path | None = None
    raven_log("DEBUG", "P4", "ingest.fn.dispatch branch chosen by extension",
              context={"filename": filename, "selected_option": suffix if suffix in (".json", ".csv", ".xml", ".xlsx") else (
                  "document" if suffix in _DOC_EXTS else "unsupported"),
                  "available_options": [".json", ".csv", ".xml", ".xlsx", "document"],
                  "reason_code": "EXTENSION", "fk_links": len(fk_links), "workspace_id": workspace_id})
    _run: dict[str, Any] = dict(
        dsn=settings.effective_dsn(),
        ontology_type=ontology_type,
        match_keys=match_keys,
        graph_url=settings.graph_url,
        broker=broker,
        on_progress=on_progress,
        fk_links=fk_links,
        workspace_id=workspace_id,
    )
    try:
        if suffix == ".json":
            tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
            tmp.write(file_bytes)
            tmp.close()
            tmp_path = Path(tmp.name)
            connector = JsonConnector(tmp_path, system="json")
            run_pipeline(connector=connector, system="json",
                         dataset=Path(filename).stem, **_run)

        elif suffix == ".csv":
            connector = CsvConnector(file_bytes, system="csv",
                                     dataset=Path(filename).stem)
            run_pipeline(connector=connector, system="csv",
                         dataset=Path(filename).stem, **_run)

        elif suffix == ".xml":
            # Ported from file_ingest_api.py's local ".xml" branch (2026-09,
            # dev-rv-msi #319): expand into one CSV per top-level element
            # type, auto-detect FK links across those derived types (scoped
            # to this one file -- OCI Functions invokes once per source
            # file, so there is no cross-file batch to consider here, unlike
            # the local path's multi-file CSV/xlsx handling), then run one
            # pipeline pass per derived type with relate/skip_graph
            # following the same is_last convention as the local path.
            from aryx.pipeline.doc_discovery import _detect_fk_links, _xml_to_csvs  # noqa: PLC0415
            from aryx.source.source_catalog import upsert_xml_catalog_entry, xml_asset_record  # noqa: PLC0415
            from aryx.store.datasource_store import DatasourceStore  # noqa: PLC0415

            orig_stem = Path(filename).stem
            xml_csvs = _xml_to_csvs(file_bytes, orig_stem)
            xml_plans = []
            for csv_data, csv_name in xml_csvs:
                csv_stem = Path(csv_name).stem
                tag = (
                    csv_stem[len(orig_stem) + 1:]
                    if csv_stem.startswith(orig_stem + "_") else csv_stem
                )
                derived_type = "".join(w.title() for w in tag.split("_") if w) or ontology_type
                xml_plans.append((csv_data, csv_name, derived_type))
            fk_plan_dicts = [
                {"data": d, "filename": n, "ontology_type": t, "match_keys": match_keys or ["name"]}
                for d, n, t in xml_plans
            ]
            auto_fk = _detect_fk_links(fk_plan_dicts)
            raven_log("DEBUG", "P4", "ingest.fn.xml plans derived",
                      context={"filename": filename, "plans": len(xml_plans), "fk_links": len(auto_fk)})
            if auto_fk:
                logger.info("fn_handler XML auto-detected %d fk-link spec(s): %s",
                            len(auto_fk), auto_fk)
            for idx, (csv_data, csv_name, derived_type) in enumerate(xml_plans):
                is_last = (idx == len(xml_plans) - 1)
                on_progress("Ingest", 20, f"Processing {csv_name}")
                run_pipeline(
                    connector=CsvConnector(csv_data, system="csv", dataset=Path(csv_name).stem),
                    system="csv", dataset=Path(csv_name).stem,
                    ontology_type=derived_type, match_keys=match_keys,
                    dsn=settings.effective_dsn(), graph_url=settings.graph_url,
                    broker=broker, on_progress=on_progress,
                    fk_links=auto_fk if is_last else [],
                    workspace_id=workspace_id,
                    relate=is_last, skip_graph=not is_last,
                )
            asset_rows = [
                xml_asset_record(
                    filename=csv_name, dataset=Path(csv_name).stem,
                    ontology_type=derived_type, content_bytes=csv_data,
                )
                for csv_data, csv_name, derived_type in xml_plans
            ]
            upsert_xml_catalog_entry(
                DatasourceStore(settings.effective_dsn()),
                workspace_id=workspace_id, source_filename=filename,
                xml_bytes=file_bytes, assets=asset_rows,
            )

        elif suffix == ".xlsx":
            # Ported from file_ingest_api.py's local ".xlsx" branch (2026-09,
            # dev-rv-msi #319).
            # KNOWN REDUCED PARITY vs. the local path: FK-link detection here
            # is scoped to THIS workbook's own sheets only. The local path
            # additionally detects FK links ACROSS every xlsx file in a
            # multi-file batch uploaded together -- that requires seeing all
            # files at once, which this per-invocation OCI Functions model
            # cannot do (file_ingest_api.py submits one function call per
            # file). If cross-workbook FK linking via this worker backend is
            # needed, the submission side would need to batch related
            # workbooks into a single invocation -- not done here.
            from aryx.pipeline.doc_discovery import _detect_fk_links, _xlsx_to_csvs  # noqa: PLC0415
            from aryx.source.source_catalog import upsert_xlsx_catalog_entry, xlsx_asset_record  # noqa: PLC0415
            from aryx.store.datasource_store import DatasourceStore  # noqa: PLC0415

            orig_stem = Path(filename).stem
            xlsx_csvs = _xlsx_to_csvs(file_bytes, orig_stem)
            if not xlsx_csvs:
                raven_log("DEBUG", "P4", "ingest.fn.xlsx no ingestible sheets",
                          context={"filename": filename, "sheets": 0, "decision": "skip"})
                logger.info("fn_handler: xlsx %r produced no ingestible sheets "
                            "(all hidden/empty)", filename)
            else:
                prefix = orig_stem + "__"
                plans = []
                for csv_data, csv_name in xlsx_csvs:
                    csv_stem = Path(csv_name).stem
                    sheet_slug = csv_stem[len(prefix):] if csv_stem.startswith(prefix) else csv_stem
                    derived_type = "".join(w.title() for w in sheet_slug.split("_") if w) or ontology_type
                    plans.append({
                        "data": csv_data, "filename": csv_name,
                        "ontology_type": derived_type,
                        "match_keys": match_keys or ["name"],
                    })
                auto_fk = _detect_fk_links(plans, log_id=filename)
                if auto_fk:
                    logger.info("fn_handler XLSX auto-detected %d fk-link spec(s): %s",
                                len(auto_fk), auto_fk)
                for idx, plan in enumerate(plans):
                    csv_data, csv_name, derived_type = plan["data"], plan["filename"], plan["ontology_type"]
                    is_last = (idx == len(plans) - 1)
                    on_progress("Ingest", 20, f"Processing {csv_name}")
                    run_pipeline(
                        connector=CsvConnector(csv_data, system="csv", dataset=Path(csv_name).stem),
                        system="csv", dataset=Path(csv_name).stem,
                        ontology_type=derived_type, match_keys=match_keys,
                        dsn=settings.effective_dsn(), graph_url=settings.graph_url,
                        broker=broker, on_progress=on_progress,
                        fk_links=auto_fk if is_last else [],
                        workspace_id=workspace_id,
                        relate=is_last, skip_graph=not is_last,
                    )
                asset_rows = [
                    xlsx_asset_record(
                        filename=plan["filename"], dataset=Path(plan["filename"]).stem,
                        ontology_type=plan["ontology_type"], content_bytes=plan["data"],
                    )
                    for plan in plans
                ]
                upsert_xlsx_catalog_entry(
                    DatasourceStore(settings.effective_dsn()),
                    workspace_id=workspace_id, source_filename=filename,
                    xlsx_bytes=file_bytes, assets=asset_rows,
                )

        elif suffix in _DOC_EXTS:
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.write(file_bytes)
            tmp.close()
            tmp_path = Path(tmp.name)
            chunk_store = ChunkStore(settings.effective_dsn())
            connector = DocumentRouterConnector(
                paths=[tmp_path],
                system="document",
                broker=broker,
                chunk_store=chunk_store,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
                expected_embed_dim=settings.embed_dim,
            )
            run_pipeline(connector=connector, system="document",
                         dataset="upload", **_run)

        else:
            raven_log("WARN", "P3", "ingest.fn.unsupported file type refused",
                      error_code="ARYX_ING_UNSUPPORTED_TYPE",
                      context={"filename": filename, "measured": suffix, "decision": "refuse",
                               "reason_code": "UNSUPPORTED_TYPE"})
            raise ValueError(f"Unsupported file type: {suffix!r}")

    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
