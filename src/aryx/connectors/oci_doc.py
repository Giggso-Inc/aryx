"""OCI Document Understanding connector — drop-in replacement for local connectors.

Returns the same (page_num, text) tuples as PdfConnector / DocxConnector so
the downstream pipeline (chunk_pages → screen_chunks → embed_chunks) is
completely unchanged.

OCI Document Understanding advantages over local parsers:
  - Layout-aware parsing: tables, key-value pairs, per-block confidence scores
  - Native scanned-PDF OCR without a local Tesseract install
  - Supports PDF, DOCX, XLSX, PPTX, images (PNG, JPG, TIFF, BMP, GIF)

Requires: oci~=2.140, ARYX_OCI_COMPARTMENT_ID set.
"""
from __future__ import annotations

import base64
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from aryx.raven_log import raven_log

logger = logging.getLogger(__name__)

# OCI Document Understanding inline document size limit (~20 MB base64 → ~15 MB raw).
# Files over this must use Object Storage upload instead of inline submission.
_OCI_INLINE_MAX_BYTES = 15 * 1024 * 1024


def _parse_oci_response(result: Any) -> dict[int, list[str]]:
    """Extract per-page text lines from an OCI Document Understanding result."""
    pages_text: dict[int, list[str]] = {}
    for block in (result.pages or []):
        page_num = block.page_number or 1
        lines = pages_text.setdefault(page_num, [])
        for line in (block.lines or []):
            if line.text:
                lines.append(line.text)
        # Tables are per-page in the OCI SDK (page.tables), not top-level.
        for table in (getattr(block, "tables", None) or []):
            for row in (table.rows or []):
                row_parts = [cell.text.strip() for cell in (row.cells or []) if cell.text]
                if row_parts:
                    lines.append(" | ".join(row_parts))
    return pages_text


class OciDocConnector:
    """Parses documents via OCI Document Understanding API."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def extract_pages(self) -> Iterator[tuple[int, str]]:
        """Yield (page_num, text) for every page using OCI Document Understanding."""
        import oci  # noqa: PLC0415
        from aryx.config import get_settings
        from aryx.oci_client import get_doc_client

        settings = get_settings()
        if not settings.oci_compartment_id:
            raven_log("ERROR", "P2", "ingest.doc.oci_du compartment missing",
                      error_code="ARYX_ING_OCI_DU_CONFIG",
                      context={"filename": self._path.name, "decision": "refuse", "reason_code": "COMPARTMENT_UNSET"})
            raise RuntimeError(
                "ARYX_OCI_COMPARTMENT_ID must be set when ARYX_PARSE_BACKEND=oci"
            )

        client = get_doc_client()
        raw = self._path.read_bytes()
        raven_log("DEBUG", "P4", "ingest.doc.oci_du size check",
                  context={"filename": self._path.name, "limit": _OCI_INLINE_MAX_BYTES, "measured": len(raw),
                           "decision": "refuse" if len(raw) > _OCI_INLINE_MAX_BYTES else "pass"})
        if len(raw) > _OCI_INLINE_MAX_BYTES:
            raven_log("ERROR", "P2", "ingest.doc.oci_du file over inline limit",
                      error_code="ARYX_ING_OCI_DU_TOO_LARGE",
                      context={"filename": self._path.name, "limit": _OCI_INLINE_MAX_BYTES, "measured": len(raw),
                               "decision": "refuse", "reason_code": "INLINE_LIMIT"})
            raise ValueError(
                f"{self._path.name!r} is {len(raw) // (1024 * 1024)} MB — "
                f"OCI Document Understanding inline limit is ~15 MB. "
                f"Use Object Storage upload for large files."
            )
        doc_b64 = base64.b64encode(raw).decode("utf-8")

        features = [
            oci.ai_document.models.DocumentTextExtractionFeature(),
            oci.ai_document.models.DocumentTableExtractionFeature(),
        ]

        inline_doc = oci.ai_document.models.InlineDocumentDetails(data=doc_b64)
        request = oci.ai_document.models.AnalyzeDocumentDetails(
            document=inline_doc,
            features=features,
            compartment_id=settings.oci_compartment_id,
        )

        response = client.analyze_document(analyze_document_details=request)
        if not response.data:
            logger.warning("oci_doc: empty response for %s", self._path.name)
            raven_log("WARN", "P3", "ingest.doc.oci_du empty response, no pages",
                      error_code="ARYX_ING_OCI_DU_EMPTY",
                      context={"filename": self._path.name, "dependency_name": "oci_document_understanding",
                               "operation": "analyze_document", "result": "empty", "attempt": 1})
            return
        pages_text = _parse_oci_response(response.data)
        raven_log("DEBUG", "P4", "ingest.doc.oci_du pages parsed",
                  context={"filename": self._path.name, "pages": len(pages_text),
                           "selected_option": "per_page" if pages_text else "top_level_text",
                           "available_options": ["per_page", "top_level_text"], "reason_code": "PAGES_PRESENT"})

        if not pages_text:
            # Fall back to top-level text if no per-page structure returned
            top_text = getattr(response.data, "text", "") or ""
            if top_text:
                yield 1, top_text
            return

        for page_num in sorted(pages_text):
            text = "\n".join(pages_text[page_num])
            if text.strip():
                yield page_num, text

    def close(self) -> None:
        pass
