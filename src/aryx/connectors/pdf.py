"""PDF document connector: text extraction + embedded image OCR (Inc 8)."""
from __future__ import annotations

import io
import logging
from collections.abc import Iterator
from pathlib import Path

from aryx.raven_log import raven_log

logger = logging.getLogger(__name__)


class PdfConnector:
    """Extracts text from PDF pages via pymupdf; OCRs embedded images via pytesseract."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def extract_pages(self) -> Iterator[tuple[int, str]]:
        """Yield (page_num, text) for every page, including OCR of embedded images."""
        import fitz  # pymupdf

        doc = fitz.open(str(self._path))
        try:
            for page_num, page in enumerate(doc, start=1):
                parts = [page.get_text()]
                images = page.get_images(full=True)
                ocr_hits = 0
                for img_info in images:
                    ocr_text = _ocr_image_bytes(doc.extract_image(img_info[0])["image"])
                    if ocr_text:
                        parts.append(ocr_text)
                        ocr_hits += 1
                raven_log("DEBUG", "P4", "ingest.doc.pdf page read",
                          context={"filename": self._path.name, "page": page_num, "images": len(images),
                                   "ocr_text_found": ocr_hits, "empty_page": not "".join(parts).strip()})
                yield page_num, "\n".join(parts)
        finally:
            doc.close()

    def close(self) -> None:
        pass


def _ocr_image_bytes(img_bytes: bytes) -> str:
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(io.BytesIO(img_bytes))
        return pytesseract.image_to_string(img).strip()
    except Exception as exc:
        logger.debug("ocr skipped: %s", exc)
        raven_log("DEBUG", "P4", "ingest.doc.ocr skipped",
                  context={"error_class": type(exc).__name__, "decision": "skip", "reason_code": "OCR_UNAVAILABLE_OR_FAILED"})
        return ""
