"""Activation check: should a given upload go through the cpq_ingestion pipeline?"""
from __future__ import annotations

import logging
from pathlib import Path

from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
from aryx.cpq_ingestion.constants import PIPELINE_CPQ_INGESTION
from aryx.raven_log import raven_log, would_log

logger = logging.getLogger(__name__)

# CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md: a layout-export
# upload (native-UI JSON, despite the historical ".txt" extension) is a
# distinct sub-flow from the XML raw-graph path -- it's stored verbatim
# for later CpqEngine lookup, never run through entity/CSV ingestion.
# Kept independent of ARYX_INGEST_FILE_TYPE (which stays XML-specific)
# so setting that to "xml" doesn't also have to somehow also mean "txt".
_LAYOUT_UPLOAD_SUFFIXES = frozenset({"txt", "json"})


def _active_file_types() -> frozenset[str]:
    """Parse ``ARYX_INGEST_FILE_TYPE`` into a set of enabled extensions.

    Comma-separated, case-insensitive, leading dot ignored on either side
    (``"xml"``, ``"XML"``, and ``".xml"`` all normalize the same way) --
    same convention as this codebase's other comma-separated config
    (``ARYX_ID_LIKE_COLUMN_NAMES``, ``ARYX_FK_KEY_SUFFIXES``). ``"xml,csv"``
    activates both file types at once, each routed by
    ``cpq_ingestion_pipeline_active()``'s callers to its own, independent
    code path (XML: raw-graph resolve/relate; CSV: direct-to-Postgres
    landing, see csv_land.py) -- one value never disables the other.
    """
    return frozenset(
        t.strip().lower().lstrip(".")
        for t in get_cpq_ingestion_settings().ingest_file_type.split(",")
        if t.strip()
    )


def cpq_ingestion_pipeline_active(filename: str) -> bool:
    """True when ``filename`` should be routed through the cpq_ingestion pipeline.

    ``ARYX_INGEST_PIPELINE`` must be ``cpq_ingestion`` (case-insensitive) and
    the file's extension must be one of ``ARYX_INGEST_FILE_TYPE``'s
    comma-separated values (case-insensitive, leading dot ignored on both
    sides). Any other combination — including both settings left at their
    empty defaults — returns False, so the existing CSV/XML paths are
    unaffected unless explicitly opted into.
    """
    settings = get_cpq_ingestion_settings()
    if not settings.ingest_file_type or not settings.ingest_pipeline:
        if would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ingest.route.cpq_pipeline inactive, flags unset",
                      context={"filename": filename, "selected_option": "standard", "reason_code": "FLAGS_UNSET",
                               "available_options": ["cpq_ingestion", "standard"],
                               "has_pipeline": bool(settings.ingest_pipeline),
                               "has_file_type": bool(settings.ingest_file_type)})
        return False
    if settings.ingest_pipeline.strip().lower() != PIPELINE_CPQ_INGESTION:
        if would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ingest.route.cpq_pipeline inactive, pipeline name differs",
                      context={"filename": filename, "selected_option": "standard",
                               "available_options": ["cpq_ingestion", "standard"],
                               "reason_code": "PIPELINE_NAME_MISMATCH", "ARYX_INGEST_PIPELINE": settings.ingest_pipeline})
        logger.debug(
            "cpq_ingestion: ARYX_INGEST_PIPELINE=%r does not match %r, not routing %s",
            settings.ingest_pipeline, PIPELINE_CPQ_INGESTION, filename,
        )
        return False
    suffix = Path(filename).suffix.lower().lstrip(".")
    active_types = _active_file_types()
    active = suffix in active_types
    if would_log("DEBUG"):
        raven_log("DEBUG", "P4", "ingest.route.cpq_pipeline decision by extension",
                  context={"filename": filename, "suffix": suffix, "active_types": sorted(active_types),
                           "selected_option": "cpq_ingestion" if active else "standard",
                           "available_options": ["cpq_ingestion", "standard"], "reason_code": "FILE_TYPE_MATCH"})
    logger.debug(
        "cpq_ingestion: routing decision for %s: suffix=%r active_types=%r active=%s",
        filename, suffix, active_types, active,
    )
    return active


def partition_cpq_ingestion_plans(
    plans: list[dict],
) -> tuple[dict[str, dict], list[dict]]:
    """Split tabular plans into (cpq_ingestion-active XML source files, the rest).

    One XML file produces one plan PER ENTITY TAG (e.g. two plans,
    ``*_PurchaseOrder.csv`` and ``*_Customer.csv``, sharing one
    ``source_filename``) -- the returned dict is keyed by ``source_filename``
    with one representative plan each (carrying ``source_bytes``, needed to
    re-derive the raw graph), not one entry per tag-plan, because
    ``resolve_and_relate_raw_graph()`` resolves every tag from one projection
    in a single call and must run once per source file, not once per plan.

    A plan with no ``source_filename`` (never derived from XML/XLSX) or a
    non-``.xml`` source never even reaches ``cpq_ingestion_pipeline_active()``.
    """
    cpq_ingestion_source_files: dict[str, dict] = {}
    remaining_plans: list[dict] = []
    for plan in plans:
        source_filename = plan.get("source_filename")
        is_xml = source_filename is not None and Path(source_filename).suffix.lower() == ".xml"
        if is_xml and cpq_ingestion_pipeline_active(source_filename):
            cpq_ingestion_source_files.setdefault(source_filename, plan)
            continue
        remaining_plans.append(plan)
    if would_log("DEBUG"):
        raven_log("DEBUG", "P4", "ingest.route.partition_xml plans split",
                  context={"plans": len(plans), "cpq_source_files": len(cpq_ingestion_source_files),
                           "remaining": len(remaining_plans), "reason_code": "XML_CPQ_ACTIVE"})
    return cpq_ingestion_source_files, remaining_plans


def partition_cpq_ingestion_csv_plans(
    plans: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Split tabular plans into (cpq_ingestion-active CSV plans, the rest).

    Unlike ``partition_cpq_ingestion_plans()`` (XML), a plain CSV upload
    needs no grouping: one uploaded file is already exactly one plan, with
    no per-entity-tag fan-out to collapse back together. The plan is marked
    ``cpq_csv_direct`` by ``read_files()`` at read time (mirroring how the
    XML branch checks ``cpq_ingestion_pipeline_active()`` inline) rather
    than re-checked here, so this function stays a pure partition, not a
    second source of the activation decision.
    """
    csv_plans = [p for p in plans if p.get("cpq_csv_direct")]
    remaining_plans = [p for p in plans if not p.get("cpq_csv_direct")]
    if would_log("DEBUG"):
        raven_log("DEBUG", "P4", "ingest.route.partition_csv plans split",
                  context={"plans": len(plans), "csv_direct": len(csv_plans), "remaining": len(remaining_plans),
                           "reason_code": "CPQ_CSV_DIRECT_FLAG"})
    return csv_plans, remaining_plans


def cpq_layout_upload_active(filename: str) -> bool:
    """True when ``filename`` should be stored as a CPQ layout file
    (aryx_cpq_layout_file) instead of run through the normal ingest
    pipeline.

    Requires BOTH ``ARYX_INGEST_PIPELINE=cpq_ingestion`` AND
    ``ARYX_CPQ_LAYOUT_SOURCE`` set -- unlike the XML raw-graph path,
    ``ingest_pipeline`` alone is deliberately NOT enough here. A
    deployment can have the master switch on for XML raw-graph writes
    without also wanting every .txt/.json upload silently diverted away
    from normal ingestion; ``cpq_layout_source`` is the explicit, second
    opt-in for that specific behavior. Keyed on its own suffix set --
    independent of ``ARYX_INGEST_FILE_TYPE``, which stays XML-specific.

    Known, deliberate trade-off: while both flags are active, ``.json``
    uploads are ALWAYS treated as layout files, never as catalog data --
    a workspace/deployment that has turned this on cannot also upload
    plain JSON catalog data through this same endpoint at the same
    time. Not a per-file, content-sniffing distinction.
    """
    settings = get_cpq_ingestion_settings()
    if settings.ingest_pipeline.strip().lower() != PIPELINE_CPQ_INGESTION:
        if would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ingest.route.layout inactive, pipeline name differs",
                      context={"filename": filename, "selected_option": "normal_ingest",
                               "available_options": ["layout_store", "normal_ingest"],
                               "reason_code": "PIPELINE_NAME_MISMATCH"})
        return False
    if not settings.cpq_layout_source.strip():
        if would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ingest.route.layout inactive, layout source unset",
                      context={"filename": filename, "selected_option": "normal_ingest",
                               "available_options": ["layout_store", "normal_ingest"],
                               "reason_code": "CPQ_LAYOUT_SOURCE_UNSET"})
        return False
    suffix = Path(filename).suffix.lower().lstrip(".")
    active = suffix in _LAYOUT_UPLOAD_SUFFIXES
    if would_log("DEBUG"):
        raven_log("DEBUG", "P4", "ingest.route.layout decision by extension",
                  context={"filename": filename, "suffix": suffix,
                           "selected_option": "layout_store" if active else "normal_ingest",
                           "available_options": ["layout_store", "normal_ingest"], "reason_code": "SUFFIX_MATCH"})
    logger.debug(
        "cpq_ingestion: layout-upload routing decision for %s: suffix=%r active=%s",
        filename, suffix, active,
    )
    return active
