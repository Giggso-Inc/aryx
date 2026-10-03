"""Pass 1: entry point wired into the existing XML upload path.

Scope (see README.md for the full write-up): ``project_raw_graph_and_flatten``
adds the raw-graph projection as a real, working capability alongside the
existing CSV flow, used at discovery/read time. Pass 2 (the resolve/relate
bridge that reads this same raw graph back and lands it in the curated
graph) lives in ``raw_graph/resolve_relate.py`` — a separate module since it
runs at a different call site (confirm time, not read time).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
from aryx.cpq_ingestion.raw_graph.store import project_and_write_raw_graph
from aryx.pipeline.doc_discovery.doc_discovery import _xml_to_csvs
from aryx.raven_log import raven_log
from aryx.worker.job_partial import note_hidden

logger = logging.getLogger(__name__)


def project_raw_graph_and_flatten(
    data: bytes,
    stem: str,
    *,
    workspace_id: int,
    dsn: str,
    graph_url: str,
    log_id: str | None = None,
    should_stop: "Callable[[], bool] | None" = None,
) -> list[tuple[bytes, str]]:
    """Project the raw graph (if enabled), then flatten XML to CSV as usual.

    This is a drop-in replacement for a direct ``_xml_to_csvs(data, stem)``
    call at the XML-upload call site: it returns the exact same
    ``[(csv_bytes, csv_filename), ...]`` shape, so every downstream step
    (auto-FK detection, per-type ``run_pipeline`` calls, catalog recording)
    is unchanged. The only added effect is the raw-graph write, gated by
    ``ARYX_CPQ_RAW_GRAPH_ENABLED`` (default on).

    Args:
        data: Raw XML document bytes.
        stem: Filename stem — used as the CSV filename prefix (matches
            ``_xml_to_csvs``) AND as the raw graph's per-file scope key, so
            that uploading several XML files to the same workspace in one
            job gives each file its own raw graph instead of each write
            clearing the previous file's (Raven review finding M1). Two
            files in the same job must not share a stem — the same
            assumption ``_xml_to_csvs``'s own CSV filenames already make.
        workspace_id: Curated workspace this upload belongs to.
        dsn: Relational store DSN, forwarded to the raw-graph writer for the
            Oracle Graph backend.
        graph_url: FalkorDB connection URL, forwarded to the raw-graph
            writer for the FalkorDB backend.
        log_id: Optional correlation id, forwarded to ``_xml_to_csvs`` for
            its own diagnostic logging.
        should_stop: Optional cancellation poll, forwarded to the raw-graph
            write (see ``write_raw_graph``'s docstring). Checked once more
            after the write returns/is skipped, below: a cancel mid-write
            leaves this file's raw graph partial and the CSV flatten step
            — a second, separately expensive pass over the same XML bytes
            — is not worth running for a job that's already stopping.

    Returns:
        Per-entity-type CSV bytes and filenames, exactly as ``_xml_to_csvs``
        produces them.
    """
    settings = get_cpq_ingestion_settings()
    t0 = time.monotonic()
    raven_log("DEBUG", "P4", "ingest.raw_graph.decision raw graph write enabled check",
              context={"stem": stem, "workspace_id": workspace_id, "log_id": log_id,
                       "selected_option": "write" if settings.cpq_raw_graph_enabled else "skip",
                       "available_options": ["write", "skip"], "reason_code": "ARYX_CPQ_RAW_GRAPH_ENABLED",
                       "flag_value": bool(settings.cpq_raw_graph_enabled)})
    if settings.cpq_raw_graph_enabled:
        try:
            result = project_and_write_raw_graph(
                data, workspace_id=workspace_id, source_key=stem, dsn=dsn, graph_url=graph_url,
                should_stop=should_stop,
            )
        except Exception as exc:  # noqa: BLE001 -- the raw graph is a best-effort provenance
            # layer alongside the primary CSV ingest path, not a precondition for it. A
            # malformed-XML parse error here must not crash the whole upload when
            # _xml_to_csvs (below) already degrades gracefully for that exact case
            # (falls back to a raw upload row and logs a warning) -- letting this
            # exception propagate would regress that existing behavior.
            logger.warning(
                "cpq_ingestion: raw graph projection/write failed stem=%s workspace_id=%s "
                "log_id=%s: %s -- continuing with CSV ingest",
                stem, workspace_id, log_id, exc,
            )
            note_hidden()
            raven_log("WARN", "P2", "ingest.raw_graph.write_failed raw graph not written, CSV ingest continues",
                      error_code="ARYX_ING_RAW_GRAPH_FAILED",
                      context={"triggering_error": type(exc).__name__, "attempt": 1, "max_attempts": 1,
                               "backoff_ms": 0, "recovery_selected": "continue_csv_ingest",
                               "fallback_target": "csv_flatten", "exit_condition": "degraded",
                               "result": "degraded", "stem": stem, "workspace_id": workspace_id,
                               "duration_ms": int((time.monotonic() - t0) * 1000)})
        else:
            raven_log("INFO", "P4", "ingest.raw_graph.written raw graph projected",
                      context={"stem": stem, "workspace_id": workspace_id, "backend": result.backend,
                               "nodes": result.nodes_written, "edges": result.edges_written,
                               "duration_ms": int((time.monotonic() - t0) * 1000)})
            logger.info(
                "cpq_ingestion: raw graph written stem=%s workspace_id=%s backend=%s %s "
                "nodes=%d edges=%d",
                stem, workspace_id, result.backend, result.graph_ref,
                result.nodes_written, result.edges_written,
            )
    else:
        logger.debug("cpq_ingestion: raw graph disabled (ARYX_CPQ_RAW_GRAPH_ENABLED=false), skipping")
    if should_stop is not None and should_stop():
        logger.warning(
            "cpq_ingestion: job cancelled — skipping CSV flatten for stem=%s workspace_id=%s",
            stem, workspace_id,
        )
        raven_log("WARN", "P3", "ingest.raw_graph.csv_skipped csv flatten skipped by cancel",
                  error_code="ARYX_ING_CANCELLED",
                  context={"stem": stem, "workspace_id": workspace_id, "selected_option": "stop",
                           "available_options": ["continue", "stop"], "reason_code": "SHOULD_STOP_TRUE"})
        return []
    return _xml_to_csvs(data, stem, log_id=log_id)
