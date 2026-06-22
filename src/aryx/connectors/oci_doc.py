"""OCI Document Understanding connector — drop-in replacement for local connectors.

Returns the same (page_num, text) tuples as PdfConnector / DocxConnector so
the downstream pipeline (chunk_pages → screen_chunks → embed_chunks) is
completely unchanged.

OCI Document Understanding advantages over local parsers:
  - Layout-aware parsing: tables, key-value pairs, per-block confidence scores
  - Native scanned-PDF OCR without a local Tesseract install
  - Supports PDF, DOCX, XLSX, PPTX, images (PNG, JPG, TIFF, BMP, GIF)

Requires: oci~=2.130, ARYX_OCI_COMPARTMENT_ID set.
"""
from __future__ import annotations

import base64
import logging
from collections.abc import Iterator
from pathlib import Path

logger = logging.getLogger(__name__)

# OCI Document Understanding feature types included in every request.
_FEATURES = ["TEXT_DETECTION", "TABLE_DETECTION"]


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
            raise RuntimeError(
                "ARYX_OCI_COMPARTMENT_ID must be set when ARYX_PARSE_BACKEND=oci"
            )

        client = get_doc_client()
        raw = self._path.read_bytes()
        doc_b64 = base64.b64encode(raw).decode("utf-8")

        features = [
            oci.ai_document.models.DocumentTextDetectionFeature(),
            oci.ai_document.models.DocumentTableDetectionFeature(),
        ]

        inline_doc = oci.ai_document.models.InlineDocumentDetails(data=doc_b64)
        request = oci.ai_document.models.AnalyzeDocumentDetails(
            document=inline_doc,
            features=features,
            compartment_id=settings.oci_compartment_id,
        )

        response = client.analyze_document(analyze_document_details=request)
        result = response.data

        pages_text: dict[int, list[str]] = {}

        # Extract text blocks per page
        for block in (result.pages or []):
            page_num = block.page_number or 1
            lines = pages_text.setdefault(page_num, [])
            for line in (block.lines or []):
                if line.text:
                    lines.append(line.text)

        # Extract table cell text per page
        for table in (result.detected_tables or []):
            page_num = getattr(table, "page_number", 1) or 1
            lines = pages_text.setdefault(page_num, [])
            for row in (table.rows or []):
                row_parts = []
                for cell in (row.cells or []):
                    if cell.text:
                        row_parts.append(cell.text.strip())
                if row_parts:
                    lines.append(" | ".join(row_parts))

        if not pages_text:
            # Fall back to top-level text if no per-page structure returned
            top_text = getattr(result, "text", "") or ""
            if top_text:
                yield 1, top_text
            return

        for page_num in sorted(pages_text):
            text = "\n".join(pages_text[page_num])
            if text.strip():
                yield page_num, text

    def close(self) -> None:
        pass
