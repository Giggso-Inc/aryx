"""Background job: ingest confirmed discovery types/files.

Split out of `api/doc_discover_api.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

import logging

from aryx import discoveries
from aryx.api.admin_api import _local_broker
from aryx.config import get_settings
from aryx.pipeline.doc_discovery import ingest_confirmed
from aryx.store.discovery_store import DiscoveryStore
from aryx.store.job_store import JobStore

logger = logging.getLogger(__name__)


def _reset_discovery_status(discovery_id: str) -> None:
    """Reset a discovery back to partial after a confirm job fails."""
    store = DiscoveryStore(get_settings().effective_dsn())
    try:
        store.set_status(discovery_id, "partial")
    except Exception:  # noqa: BLE001
        pass
    finally:
        store.close()


def _confirm_job(did: str, types: list[str], files: list[str], job_id: str,
                 workspace_id: int = 1, restart: bool = False) -> None:
    settings = get_settings()
    jobs = JobStore(settings.effective_dsn())
    try:
        data = discoveries.get(did, workspace_id)
        if not data:
            logger.warning("confirm job=%s discovery not found did=%s workspace=%d",
                           job_id, did, workspace_id)
            jobs.finish(job_id, run_id=None, status="failed",
                        error=f"discovery {did} not found or workspace mismatch")
            return
        confirm_state: dict = {} if restart else data.get("_confirm_state", {})
        logger.info("doc confirm start did=%s job=%s types=%s files=%s", did, job_id, types, files)
        ingest_confirmed(data, types, files, _local_broker(), jobs, job_id,
                         workspace_id, confirm_state=confirm_state, discovery_id=did)
        jobs.finish(job_id, run_id=None, status="complete")
        discoveries.mark_confirmed(did, job_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("doc confirm failed job=%s: %s", job_id, exc, exc_info=True)
        jobs.finish(job_id, run_id=None, status="failed", error=str(exc))
        _reset_discovery_status(did)
    finally:
        jobs.close()
