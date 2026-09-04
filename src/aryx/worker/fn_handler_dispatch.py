"""Per-file connector routing for the OCI Functions ingest handler.

Split out of `worker/fn_handler.py` (Raven Style Compliance Plan, Phase
2b, 2026-09-03). Zero test patches against this module (this file has no
importers/tests at all — confirmed via grep) — the split was purely
mechanical.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DOC_EXTS = {
    ".pdf", ".pptx", ".ppt", ".docx", ".doc", ".rtf",
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp",
}


def _dispatch(
    suffix: str,
    file_bytes: bytes,
    filename: str,
    settings: Any,
    broker: Any,
    on_progress: Any,
    ontology_type: str,
    match_keys: list,
    fk_links: list,
    workspace_id: int,
) -> None:
    """Route one file to the correct connector and run the full ingest pipeline."""
    from aryx.connectors.csv_source import CsvConnector  # noqa: PLC0415
    from aryx.connectors.doc_router import DocumentRouterConnector  # noqa: PLC0415
    from aryx.connectors.json_source import JsonConnector  # noqa: PLC0415
    from aryx.pipeline.orchestrate import run_pipeline  # noqa: PLC0415
    from aryx.store.chunk_store import ChunkStore  # noqa: PLC0415

    tmp_path: Path | None = None
    _run: dict[str, Any] = dict(
        dsn=settings.effective_dsn(),
        ontology_type=ontology_type,
        match_keys=match_keys,
        graph_url=settings.graph_url,
        broker=broker,
        on_progress=on_progress,
        fk_links=fk_links,
        workspace_id=workspace_id,
    )
    try:
        if suffix == ".json":
            tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
            tmp.write(file_bytes)
            tmp.close()
            tmp_path = Path(tmp.name)
            connector = JsonConnector(tmp_path, system="json")
            run_pipeline(connector=connector, system="json",
                         dataset=Path(filename).stem, **_run)

        elif suffix == ".csv":
            connector = CsvConnector(file_bytes, system="csv",
                                     dataset=Path(filename).stem)
            run_pipeline(connector=connector, system="csv",
                         dataset=Path(filename).stem, **_run)

        elif suffix in _DOC_EXTS:
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.write(file_bytes)
            tmp.close()
            tmp_path = Path(tmp.name)
            chunk_store = ChunkStore(settings.effective_dsn())
            connector = DocumentRouterConnector(
                paths=[tmp_path],
                system="document",
                broker=broker,
                chunk_store=chunk_store,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
                expected_embed_dim=settings.embed_dim,
            )
            run_pipeline(connector=connector, system="document",
                         dataset="upload", **_run)

        else:
            raise ValueError(f"Unsupported file type: {suffix!r}")

    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
