"""Document router: per-type connectors → chunk → PII → embed → extract (Inc 8)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed
from pathlib import Path

from aryx.broker import Broker
from aryx.connectors.base import Connector
from aryx.connectors.docx import DocxConnector
from aryx.connectors.image import ImageConnector, SUPPORTED_EXTENSIONS as IMAGE_EXTS
from aryx.connectors.markup import MarkupConnector
from aryx.connectors.pdf import PdfConnector
from aryx.connectors.pptx import PptxConnector
from aryx.models import RawRecord, SourceRef
from aryx.ontology.extract import extract_mentions
from aryx.pipeline.clean_text import chunk_pages
from aryx.pipeline.embed import embed_chunks
from aryx.pipeline.pii import screen_chunks
from aryx.config import get_settings
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


# OCI Document Understanding supported types (PDF, Office docs, images).
# Markup types (.xml, .html, .htm) are NOT supported — handled locally.
_OCI_DOC_EXTS = {
    ".pdf",
    ".docx", ".doc", ".rtf",
    ".pptx", ".ppt",
    *IMAGE_EXTS,
}


def _connector_for(path: Path):
    from aryx.config import get_settings
    if get_settings().effective_parse_backend() == "oci":
        if path.suffix.lower() in _OCI_DOC_EXTS:
            from aryx.connectors.oci_doc import OciDocConnector  # noqa: PLC0415
            return OciDocConnector(path)
        # .xml / .html / .htm not supported by OCI DU — fall through to local connector.
    cls = _EXT_MAP.get(path.suffix.lower())
    if cls is None:
        raise ValueError(f"unsupported document type: {path.suffix!r}")
    return cls(path)


# Hard wall-clock budget per document — a hang in parse / OCR / embed /
# extract is abandoned so the batch finishes. Override with ARYX_PER_DOC_TIMEOUT.
_PER_DOC_TIMEOUT = get_settings().per_doc_timeout

# Max documents processed concurrently. Default 1 (sequential) for CPU Ollama
# where parallelism adds queue overhead without throughput gain. Set to 3-5
# when using a cloud LLM (Anthropic/OpenAI) that handles concurrent requests.
_DOC_WORKERS = get_settings().doc_workers


def _log_timed_out(path: Path, elapsed: float) -> None:
    """Log a FuturesTimeout with the real elapsed time, not the configured budget.

    future.result(timeout=_PER_DOC_TIMEOUT) raises the same TimeoutError whether
    the outer per-document budget genuinely expired, or an inner call (e.g. the
    embedding HTTP request) already failed with its own, shorter timeout — since
    Python unifies socket.timeout/TimeoutError/concurrent.futures.TimeoutError
    into one class. Elapsed time distinguishes the two: it will sit near
    _PER_DOC_TIMEOUT for a genuine outer expiry, and well under it when an inner
    call is what actually failed.
    """
    if elapsed >= _PER_DOC_TIMEOUT * 0.95:
        logger.error(
            "ingest TIMED OUT path=%s after %.1fs — exceeded the per-document "
            "budget (ARYX_PER_DOC_TIMEOUT=%ss); skipping; batch continues",
            path.name, elapsed, _PER_DOC_TIMEOUT,
        )
    else:
        logger.error(
            "ingest TIMED OUT path=%s after %.1fs — an inner call timed out well "
            "before the %ss per-document budget (ARYX_PER_DOC_TIMEOUT); "
            "skipping; batch continues",
            path.name, elapsed, _PER_DOC_TIMEOUT,
        )


def _ingest_with_timeout(
    path: Path, system: str, broker: Broker, chunk_store: ChunkStore,
    chunk_size: int, chunk_overlap: int, expected_embed_dim: int,
    run_pii: bool, context: str,
    on_progress: Callable[[int, int, list[RawRecord]], None] | None = None,
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
    on_progress: Callable[[int, int, list[RawRecord]], None] | None = None,
) -> list[RawRecord]:
    doc_id = _content_hash(path)
    source = SourceRef(system=system, dataset=path.stem, record_id=doc_id)
    pages = list(_connector_for(path).extract_pages())
    logger.info("[step 1/8] pages=%d  path=%s", len(pages), path.name)
    chunks = chunk_pages(pages, source=source, doc_id=doc_id,
                         chunk_size=chunk_size, overlap=chunk_overlap)
    logger.info("[step 2/8] chunks=%d  doc_id=%s", len(chunks), doc_id[:8])
    if run_pii:
        logger.info("[step 3/8] pii screening  chunks=%d", len(chunks))
        chunks = screen_chunks(chunks)
    doc_db_id = chunk_store.upsert_document(
        content_hash=doc_id, file_name=path.name,
        source_type=path.suffix.lstrip(".").lower(),
        byte_count=path.stat().st_size,
    )
    logger.info("[step 4/8] doc saved  doc_db_id=%d", doc_db_id)
    chunk_db_ids = chunk_store.save_chunks(doc_db_id, chunks)
    logger.info("[step 5/8] chunks saved  ids=%d", len(chunk_db_ids))
    logger.info("[step 6/8] embedding  chunks=%d", len(chunks))
    embeddings = embed_chunks(chunks, broker, expected_dim=expected_embed_dim)
    logger.info("[step 7/8] embeddings=%d  saving to db", len(embeddings))
    chunk_store.save_embeddings(chunk_db_ids, embeddings)
    logger.info("[step 8/8] extracting mentions  chunks=%d", len(chunks))
    records = extract_mentions(chunks, broker, context=context, on_progress=on_progress)
    logger.info("[ingest done] path=%s  chunks=%d  mentions=%d  doc_id=%s",
                path.name, len(chunks), len(records), doc_id[:8])
    return records


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

    def extract(self) -> Iterator[RawRecord]:
        if _DOC_WORKERS <= 1 or len(self._paths) <= 1:
            for path in self._paths:
                start = time.monotonic()
                try:
                    yield from _ingest_with_timeout(
                        path, self._system, self._broker, self._chunk_store,
                        self._chunk_size, self._chunk_overlap,
                        self._expected_embed_dim, self._run_pii, self._context,
                        self._on_progress,
                    )
                except FuturesTimeout:
                    _log_timed_out(path, time.monotonic() - start)
                except Exception as exc:
                    logger.error("ingest failed path=%s error=%s", path.name, exc)
        else:
            # Parallel mode: ARYX_DOC_WORKERS > 1 (use with cloud LLMs only).
            # All docs are submitted concurrently; results yielded as each finishes.
            logger.info("parallel doc ingest workers=%d docs=%d",
                        _DOC_WORKERS, len(self._paths))
            with ThreadPoolExecutor(max_workers=_DOC_WORKERS) as pool:
                batch_start = time.monotonic()
                futures = {
                    pool.submit(
                        _ingest_with_timeout,
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
                    except FuturesTimeout:
                        _log_timed_out(path, time.monotonic() - batch_start)
                    except Exception as exc:
                        logger.error("ingest failed path=%s error=%s", path.name, exc)


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
        else:
            all_records.extend(result)
    return all_records
