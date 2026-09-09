"""Background job: read uploaded documents into a discovery snapshot.

Split out of `api/doc_discover_api.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile

from aryx import discoveries
from aryx.api.admin_api import _local_broker
from aryx.config import get_settings
from aryx.pipeline.doc_discovery.doc_discovery import DATA_EXTS, DOC_EXTS, read_files
from aryx.store.job_store import JobStore

logger = logging.getLogger(__name__)


def _save_tmp(data: bytes, suffix: str) -> Path:
    tmp = NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(data)
    tmp.close()
    return Path(tmp.name)


def _build_read_progress(jobs: JobStore, did: str, workspace_id: int) -> Callable[[int, int, list], None]:
    """Build the extract_mentions() progress callback for a read job.

    Durability: on very large (1000+ page) documents, per_doc_timeout can
    expire — or the process can crash — before extraction finishes. Before
    this callback existed, the full mention list was only handed back at the
    very end of read_files(), so any interruption mid-run lost every mention
    extracted so far with nothing recoverable. This callback instead
    persists a growing partial discovery snapshot after every flush, and
    reports real chunk-level progress to the job store (instead of a single
    static "Reading 30%" that never moves until the whole read finishes) --
    the same durability gap and stuck-progress-bar symptom that made a long
    read look identical to a hang.

    Thread safety: with ARYX_DOC_WORKERS > 1, multiple documents' extraction
    threads can call this concurrently — guarded by a lock.
    """
    lock = threading.Lock()
    accumulated: list = []

    def _on_progress(completed: int, total: int, new_records: list) -> None:
        with lock:
            accumulated.extend(new_records)
            pct = 30 + int(min(completed / max(total, 1), 1.0) * 60)
            jobs.update_stage(did, "Reading", min(pct, 90),
                              f"Extracted {completed}/{total} chunk(s)…")
            by_type: dict[str, list[str]] = {}
            for m in accumulated:
                by_type.setdefault(m.payload["type"], []).append(m.payload["name"])
            types = [{"type": t, "count": len(v), "examples": list(dict.fromkeys(v))[:5]}
                     for t, v in sorted(by_type.items(), key=lambda kv: -len(kv[1]))]
            discoveries.put(did, {
                "mentions": list(accumulated), "tabular": [],
                "summary": {"types": types, "files": []},
                "workspace_id": workspace_id, "partial": True,
            })

    return _on_progress


def _read_job(items: list[tuple[bytes, str]], context: str, did: str,
              workspace_id: int = 1) -> None:
    settings = get_settings()
    jobs = JobStore(settings.effective_dsn())
    try:
        jobs.update_stage(did, "Reading", 30, f"Reading {len(items)} file(s)…")
        logger.info("doc read start did=%s files=%d context=%r", did, len(items), context)
        doc_paths = [_save_tmp(d, Path(n).suffix) for d, n in items
                     if Path(n).suffix.lower() in DOC_EXTS]
        tabular = [(d, n) for d, n in items if Path(n).suffix.lower() in DATA_EXTS]
        on_progress = _build_read_progress(jobs, did, workspace_id)
        result = read_files(doc_paths, tabular, _local_broker(), context, did=did,
                            on_progress=on_progress)
        result["workspace_id"] = workspace_id
        discoveries.put(did, result, workspace_id)
        logger.info("doc read complete did=%s mentions=%d tabular_files=%d types=%d",
                    did, len(result.get("mentions", [])), len(result.get("tabular", [])),
                    len(result.get("summary", {}).get("types", [])))
        jobs.finish(did, run_id=None, status="complete")
    except Exception as exc:  # noqa: BLE001
        logger.warning("doc read failed did=%s: %s", did, exc, exc_info=True)
        jobs.finish(did, run_id=None, status="failed", error=str(exc))
    finally:
        jobs.close()
