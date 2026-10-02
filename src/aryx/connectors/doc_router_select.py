"""Per-extension connector selection (local vs. OCI Document Understanding).

Split out of `connectors/doc_router.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from aryx.connectors.base import Connector
from aryx.raven_log import raven_log
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
    backend = get_settings().effective_parse_backend()
    if backend == "oci":
        if path.suffix.lower() in _OCI_DOC_EXTS:
            from aryx.connectors.oci_doc import OciDocConnector  # noqa: PLC0415
            raven_log("DEBUG", "P4", "ingest.doc.reader chosen OCI Document Understanding",
                      context={"filename": path.name, "suffix": path.suffix.lower(), "selected_option": "oci_du",
                               "available_options": ["oci_du", "local"], "reason_code": "PARSE_BACKEND_OCI_SUPPORTED",
                               "parse_backend": backend})
            return OciDocConnector(path)
        # .xml / .html / .htm not supported by OCI DU — fall through to local connector.
    cls = _EXT_MAP.get(path.suffix.lower())
    if cls is None:
        raven_log("WARN", "P3", "ingest.doc.reader no connector for extension",
                  error_code="ARYX_ING_UNSUPPORTED_DOC",
                  context={"filename": path.name, "suffix": path.suffix.lower(), "decision": "refuse",
                           "reason_code": "UNSUPPORTED_DOC_TYPE", "parse_backend": backend})
        raise ValueError(f"unsupported document type: {path.suffix!r}")
    raven_log("DEBUG", "P4", "ingest.doc.reader chosen local connector",
              context={"filename": path.name, "suffix": path.suffix.lower(), "selected_option": cls.__name__,
                       "available_options": ["oci_du", "local"],
                       "reason_code": "LOCAL_BACKEND" if backend != "oci" else "OCI_UNSUPPORTED_EXTENSION",
                       "parse_backend": backend})
    return cls(path)
