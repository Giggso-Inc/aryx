"""Activation check: should a given upload go through the cpq_ingestion pipeline?"""
from __future__ import annotations

import logging
from pathlib import Path

from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
from aryx.cpq_ingestion.constants import PIPELINE_CPQ_INGESTION

logger = logging.getLogger(__name__)


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
