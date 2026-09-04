"""Per-extension connector selection (local vs. OCI Document Understanding).

Split out of `connectors/doc_router.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from aryx.connectors.base import Connector
from aryx.connectors.docx import DocxConnector
from aryx.connectors.image import ImageConnector, SUPPORTED_EXTENSIONS as IMAGE_EXTS
from aryx.connectors.markup import MarkupConnector
from aryx.connectors.pdf import PdfConnector
from aryx.connectors.pptx import PptxConnector

_EXT_MAP: dict[str, type] = {
    ".pdf": PdfConnector,
    ".pptx": PptxConnector, ".ppt": PptxConnector,
    ".docx": DocxConnector, ".doc": DocxConnector, ".rtf": DocxConnector,
    ".xml": MarkupConnector, ".html": MarkupConnector, ".htm": MarkupConnector,
    **{ext: ImageConnector for ext in IMAGE_EXTS},
}

# OCI Document Understanding supported types (PDF, Office docs, images).
# Markup types (.xml, .html, .htm) are NOT supported — handled locally.
_OCI_DOC_EXTS = {
    ".pdf",
    ".docx", ".doc", ".rtf",
    ".pptx", ".ppt",
    *IMAGE_EXTS,
}


def _content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _connector_for(path: Path) -> Connector:
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
