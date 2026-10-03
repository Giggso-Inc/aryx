"""Document router: per-type connectors → chunk → PII → embed → extract (Inc 8).

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`doc_router_select.py` (per-extension connector selection) and
`doc_router_ingest.py` (the single-document ingest pipeline + hard
wall-clock timeout wrapper), both re-imported here. Zero whitebox test
patches exist anywhere against `aryx.connectors.doc_router.*` (confirmed
via grep), so the split was purely mechanical. `DocumentRouterConnector`
and `ingest_documents_parallel` — the multi-document orchestration —
stay here.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed
from pathlib import Path

from aryx.broker import Broker
from aryx.connectors.base import Connector
from aryx.connectors.doc_router_ingest import (
    _DOC_WORKERS,
    _PER_DOC_TIMEOUT,
    _ingest_with_timeout,
    _log_timed_out,
    ingest_document,
)
from aryx.models import RawRecord
from aryx.raven_log import raven_log, submit_ctx
from aryx.worker.job_partial import note_hidden
from aryx.store.chunk_store import ChunkStore

__all__ = [
    "DocumentRouterConnector",
    "ingest_document",
    "ingest_documents_parallel",
]

logger = logging.getLogger(__name__)


class DocumentRouterConnector(Connector):
    """Plugs the document pipeline into discover() via the Connector ABC."""

    def __init__(
        self, paths: list[Path], system: str, broker: Broker,
        chunk_store: ChunkStore, chunk_size: int = 1000,
        chunk_overlap: int = 100, expected_embed_dim: int = 768,
        run_pii: bool = True, context: str = "",
        on_progress: Callable[[int, int, list[RawRecord]], None] | None = None,
    ) -> None:
        self._paths = paths
        self._system = system
        self._broker = broker
        self._chunk_store = chunk_store
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._expected_embed_dim = expected_embed_dim
        self._run_pii = run_pii
        self._context = context
        self._on_progress = on_progress

    def _summary(self, t0: float, ok: int, failed: list[str], timed_out: list[str]) -> None:
        """Emit the one ingest.docs.summary record after the document loop."""
        skipped = failed + timed_out
        if skipped:
            note_hidden()
        raven_log("WARN" if skipped else "INFO", "P2" if skipped else "P4",
                  "ingest.docs.summary documents finished" + (" with skips" if skipped else ""),
                  error_code="ARYX_ING_DOCS_SKIPPED" if skipped else "",
                  context={"task_id": "documents", "final_status": "partial" if skipped else "complete",
                           "duration_ms": int((time.monotonic() - t0) * 1000), "stage": "documents",
                           "result": "partial" if skipped else "ok",
                           "reason_code": "DOCS_SKIPPED" if skipped else "ALL_DOCS_OK",
                           "impact_scope": {"docs_total": len(self._paths), "docs_ok": ok,
                                            "docs_failed": len(failed), "docs_timed_out": len(timed_out),
                                            "skipped_names": (failed + timed_out)[:20]}})

    def extract(self) -> Iterator[RawRecord]:
        t0 = time.monotonic()
        ok = 0
        failed: list[str] = []
        timed_out: list[str] = []
        parallel = not (_DOC_WORKERS <= 1 or len(self._paths) <= 1)
        raven_log("DEBUG", "P4", "ingest.docs.mode sequential or parallel",
                  context={"selected_option": "parallel" if parallel else "sequential",
                           "available_options": ["parallel", "sequential"], "reason_code": "DOC_WORKERS_AND_COUNT",
                           "doc_workers": _DOC_WORKERS, "docs": len(self._paths), "per_doc_timeout_s": _PER_DOC_TIMEOUT})
        if not parallel:
            for path in self._paths:
                start = time.monotonic()
                try:
                    yield from _ingest_with_timeout(
                        path, self._system, self._broker, self._chunk_store,
                        self._chunk_size, self._chunk_overlap,
                        self._expected_embed_dim, self._run_pii, self._context,
                        self._on_progress,
                    )
                    ok += 1
                except FuturesTimeout:
                    timed_out.append(path.name)
                    _log_timed_out(path, time.monotonic() - start)
                except Exception as exc:
                    failed.append(path.name)
                    logger.error("ingest failed path=%s error=%s", path.name, exc)
                    raven_log("DEBUG", "P4", "ingest.doc.failed document skipped",
                              context={"filename": path.name, "error_class": type(exc).__name__,
                                       "duration_ms": int((time.monotonic() - start) * 1000)})
        else:
            # Parallel mode: ARYX_DOC_WORKERS > 1 (use with cloud LLMs only).
            # All docs are submitted concurrently; results yielded as each finishes.
            logger.info("parallel doc ingest workers=%d docs=%d",
                        _DOC_WORKERS, len(self._paths))
            with ThreadPoolExecutor(max_workers=_DOC_WORKERS) as pool:
                batch_start = time.monotonic()
                futures = {
                    submit_ctx(
                        pool, _ingest_with_timeout,
                        path, self._system, self._broker, self._chunk_store,
                        self._chunk_size, self._chunk_overlap,
                        self._expected_embed_dim, self._run_pii, self._context,
                        self._on_progress,
                    ): path
                    for path in self._paths
                }
                for future in as_completed(futures):
                    path = futures[future]
                    try:
                        yield from future.result()
                        ok += 1
                    except FuturesTimeout:
                        timed_out.append(path.name)
                        _log_timed_out(path, time.monotonic() - batch_start)
                    except Exception as exc:
                        failed.append(path.name)
                        logger.error("ingest failed path=%s error=%s", path.name, exc)
                        raven_log("DEBUG", "P4", "ingest.doc.failed document skipped",
                                  context={"filename": path.name, "error_class": type(exc).__name__})
        self._summary(t0, ok, failed, timed_out)


async def ingest_documents_parallel(
    paths: list[Path], system: str, broker: Broker, chunk_store: ChunkStore,
    chunk_size: int = 1000, chunk_overlap: int = 100,
    expected_embed_dim: int = 768, run_pii: bool = True,
    on_progress: Callable[[int, int, list[RawRecord]], None] | None = None,
) -> list[RawRecord]:
    loop = asyncio.get_running_loop()
    tasks = [
        loop.run_in_executor(
            None, lambda p=path: ingest_document(
                p, system, broker, chunk_store,
                chunk_size, chunk_overlap, expected_embed_dim, run_pii,
                "", on_progress,
            ),
        )
        for path in paths
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_records: list[RawRecord] = []
    for path, result in zip(paths, results):
        if isinstance(result, Exception):
            logger.error("parallel ingest failed path=%s error=%s", path.name, result)
            raven_log("WARN", "P2", "ingest.docs.summary parallel document failed",
                      error_code="ARYX_ING_DOCS_SKIPPED",
                      context={"filename": path.name, "error_class": type(result).__name__,
                               "stage": "documents", "result": "partial", "reason_code": "DOC_FAILED"})
        else:
            all_records.extend(result)
    raven_log("DEBUG", "P4", "ingest.docs.parallel finished",
              context={"docs": len(paths), "records": len(all_records), "stage": "documents"})
    return all_records
