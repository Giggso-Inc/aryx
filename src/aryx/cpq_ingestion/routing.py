"""Activation check: should a given upload go through the cpq_ingestion pipeline?"""
from __future__ import annotations

import logging
from pathlib import Path

from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
from aryx.cpq_ingestion.constants import PIPELINE_CPQ_INGESTION

logger = logging.getLogger(__name__)

# CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md: a layout-export
# upload (native-UI JSON, despite the historical ".txt" extension) is a
# distinct sub-flow from the XML raw-graph path -- it's stored verbatim
# for later CpqEngine lookup, never run through entity/CSV ingestion.
# Kept independent of ARYX_INGEST_FILE_TYPE (which stays XML-specific)
# so setting that to "xml" doesn't also have to somehow also mean "txt".
_LAYOUT_UPLOAD_SUFFIXES = frozenset({"txt", "json"})


def cpq_ingestion_pipeline_active(filename: str) -> bool:
    """True when ``filename`` should be routed through the cpq_ingestion pipeline.

    Both ``ARYX_INGEST_FILE_TYPE`` and ``ARYX_INGEST_PIPELINE`` must be set,
    and the pipeline must be ``cpq_ingestion`` (case-insensitive) and the
    file's extension must match the configured file type (case-insensitive,
    leading dot ignored on both sides). Any other combination — including
    both settings left at their empty defaults — returns False, so the
    existing XML->CSV path is unaffected unless explicitly opted into.
    """
    settings = get_cpq_ingestion_settings()
    if not settings.ingest_file_type or not settings.ingest_pipeline:
        return False
    if settings.ingest_pipeline.strip().lower() != PIPELINE_CPQ_INGESTION:
        logger.debug(
            "cpq_ingestion: ARYX_INGEST_PIPELINE=%r does not match %r, not routing %s",
            settings.ingest_pipeline, PIPELINE_CPQ_INGESTION, filename,
        )
        return False
    suffix = Path(filename).suffix.lower().lstrip(".")
    configured_type = settings.ingest_file_type.strip().lower().lstrip(".")
    active = suffix == configured_type
    logger.debug(
        "cpq_ingestion: routing decision for %s: suffix=%r configured_type=%r active=%s",
        filename, suffix, configured_type, active,
    )
    return active


def cpq_layout_upload_active(filename: str) -> bool:
    """True when ``filename`` should be stored as a CPQ layout file
    (aryx_cpq_layout_file) instead of run through the normal ingest
    pipeline. Gated on the same ``ARYX_INGEST_PIPELINE=cpq_ingestion``
    master switch as the XML raw-graph path, but keyed on its own
    suffix set -- independent of ``ARYX_INGEST_FILE_TYPE``, which stays
    XML-specific.

    Known, deliberate trade-off: while this master switch is active,
    ``.json`` uploads are ALWAYS treated as layout files, never as
    catalog data -- a workspace/deployment that has turned this switch
    on for CPQ layout+XML ingestion cannot also upload plain JSON
    catalog data through this same endpoint at the same time. This
    mirrors the switch's existing all-or-nothing shape (it already
    replaces this deployment's normal ingestion behavior for its
    configured file type); it is not a per-file, content-sniffing
    distinction.
    """
    settings = get_cpq_ingestion_settings()
    if settings.ingest_pipeline.strip().lower() != PIPELINE_CPQ_INGESTION:
        return False
    suffix = Path(filename).suffix.lower().lstrip(".")
    active = suffix in _LAYOUT_UPLOAD_SUFFIXES
    logger.debug(
        "cpq_ingestion: layout-upload routing decision for %s: suffix=%r active=%s",
        filename, suffix, active,
    )
    return active
