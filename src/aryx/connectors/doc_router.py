"""Document router: per-type connectors → chunk → PII → embed → extract (Inc 8)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path

from aryx.broker import Broker
from aryx.connectors.base import Connector
from aryx.connectors.docx import DocxConnector
from aryx.connectors.image import ImageConnector, SUPPORTED_EXTENSIONS as IMAGE_EXTS
from aryx.connectors.markup import MarkupConnector
from aryx.connectors.pdf import PdfConnector
from aryx.connectors.pptx import PptxConnector
from aryx.models import RawRecord, SourceRef
from aryx.ontology.extract import OnProgress, extract_mentions
from aryx.pipeline.clean_text import chunk_pages
from aryx.pipeline.embed import embed_chunks
from aryx.pipeline.pii import screen_chunks
from aryx.store.chunk_store import ChunkStore

logger = logging.getLogger(__name__)

_EXT_MAP: dict[str, type] = {
    ".pdf": PdfConnector,
    ".pptx": PptxConnector, ".ppt": PptxConnector,
    ".docx": DocxConnector, ".doc": DocxConnector, ".rtf": DocxConnector,
    ".xml": MarkupConnector, ".html": MarkupConnector, ".htm": MarkupConnector,
    **{ext: ImageConnector for ext in IMAGE_EXTS},
}


def _content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _connector_for(path: Path):
    cls = _EXT_MAP.get(path.suffix.lower())
    if cls is None:
        raise ValueError(f"unsupported document type: {path.suffix!r}")
    return cls(path)


# Hard wall-clock budget per document — a hang in parse / OCR / embed /
# extract is abandoned so the batch finishes. Override ARYX_PER_DOC_TIMEOUT.
_PER_DOC_TIMEOUT = float(os.environ.get("ARYX_PER_DOC_TIMEOUT", "300"))


def _ingest_with_timeout(
    path: Path, system: str, broker: Broker, chunk_store: ChunkStore,
    chunk_size: int, chunk_overlap: int, expected_embed_dim: int,
    run_pii: bool, context: str, on_progress: OnProgress | None = None,
) -> list[RawRecord]:
    """ingest_document under a hard timeout; raises FuturesTimeout on hang."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            ingest_document, path, system, broker, chunk_store,
            chunk_size, chunk_overlap, expected_embed_dim, run_pii, context,
            on_progress,
        )
        return future.result(timeout=_PER_DOC_TIMEOUT)


def ingest_document(
    path: Path, system: str, broker: Broker, chunk_store: ChunkStore,
    chunk_size: int, chunk_overlap: int, expected_embed_dim: int,
    run_pii: bool = True, context: str = "",
    on_progress: OnProgress | None = None,
) -> list[RawRecord]:
    doc_id = _content_hash(path)
    source = SourceRef(system=system, dataset=path.stem, record_id=doc_id)
    pages = list(_connector_for(path).extract_pages())
    chunks = chunk_pages(pages, source=source, doc_id=doc_id,
                         chunk_size=chunk_size, overlap=chunk_overlap)
    if run_pii:
        chunks = screen_chunks(chunks)
    doc_db_id = chunk_store.upsert_document(
        content_hash=doc_id, file_name=path.name,
        source_type=path.suffix.lstrip(".").lower(),
        byte_count=path.stat().st_size,
    )
    chunk_db_ids = chunk_store.save_chunks(doc_db_id, chunks)
    embeddings = embed_chunks(chunks, broker, expected_dim=expected_embed_dim)
    chunk_store.save_embeddings(chunk_db_ids, embeddings)
    records = extract_mentions(chunks, broker, context=context, on_progress=on_progress)
    logger.info("ingest_document path=%s doc_id=%s chunks=%d mentions=%d",
                path.name, doc_id[:8], len(chunks), len(records))
    return records


class DocumentRouterConnector(Connector):
    """Plugs the document pipeline into discover() via the Connector ABC."""

    def __init__(
        self, paths: list[Path], system: str, broker: Broker,
        chunk_store: ChunkStore, chunk_size: int = 1000,
        chunk_overlap: int = 100, expected_embed_dim: int = 768,
        run_pii: bool = True, context: str = "",
        on_progress: OnProgress | None = None,
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

    def extract(self) -> Iterator[RawRecord]:
        for path in self._paths:
            started = time.monotonic()
            try:
                yield from _ingest_with_timeout(
                    path, self._system, self._broker, self._chunk_store,
                    self._chunk_size, self._chunk_overlap,
                    self._expected_embed_dim, self._run_pii, self._context,
                    self._on_progress,
                )
            except FuturesTimeout:
                # NOTE: socket.timeout (e.g. a slow embed/LLM HTTP call) is
                # the SAME class as concurrent.futures.TimeoutError since
                # Python 3.11 — this except also catches those, not just a
                # genuine ARYX_PER_DOC_TIMEOUT budget exhaustion. Report the
                # real measured elapsed time so a short-lived inner timeout
                # (e.g. a slow embedding call) isn't misreported as having
                # run for the full per-document budget.
                elapsed = time.monotonic() - started
                logger.error(
                    "ingest TIMED OUT path=%s after %.1fs (budget=%ss) — "
                    "skipping; batch continues", path.name, elapsed, _PER_DOC_TIMEOUT)
            except Exception as exc:
                logger.error("ingest failed path=%s error=%s", path.name, exc)


async def ingest_documents_parallel(
    paths: list[Path], system: str, broker: Broker, chunk_store: ChunkStore,
    chunk_size: int = 1000, chunk_overlap: int = 100,
    expected_embed_dim: int = 768, run_pii: bool = True,
) -> list[RawRecord]:
    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(
            None, lambda p=path: ingest_document(
                p, system, broker, chunk_store,
                chunk_size, chunk_overlap, expected_embed_dim, run_pii,
            ),
        )
        for path in paths
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_records: list[RawRecord] = []
    for path, result in zip(paths, results):
        if isinstance(result, Exception):
            logger.error("parallel ingest failed path=%s error=%s", path.name, result)
        else:
            all_records.extend(result)
    return all_records
