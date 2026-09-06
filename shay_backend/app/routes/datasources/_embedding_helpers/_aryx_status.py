"""Best-effort live Aryx job status lookup, additive only to a datasource response."""

import logging
from typing import Any, Dict, Optional

from app.routes.aryx import call_aryx_job_status

logger = logging.getLogger(__name__)


async def _aryx_ingestion_status_for(datasource_metadata: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Best-effort live Aryx job status for a datasource, additive only.

    Returns None (never raises) unless datasource_metadata carries an
    aryx.discovery_id — i.e. this datasource was created via a kind="aryx"
    bulk upload. A datasource without that key is completely unaffected;
    a transient Aryx-unreachable error degrades to None rather than failing
    the caller's whole response.
    """
    if not datasource_metadata:
        return None
    aryx_meta = datasource_metadata.get("aryx")
    if not isinstance(aryx_meta, dict):
        return None
    discovery_id = aryx_meta.get("discovery_id")
    if not discovery_id:
        return None
    try:
        return await call_aryx_job_status(discovery_id)
    except Exception as exc:  # noqa: BLE001 — status enrichment must never break the caller
        logger.warning("aryx_ingestion_status lookup failed for discovery_id=%s: %s", discovery_id, exc)
        return {"error": "status temporarily unavailable"}
