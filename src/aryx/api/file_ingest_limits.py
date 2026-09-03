"""File-ingest size/type limits shared by the router and the ingest worker.

Split out of `api/file_ingest_api.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

_DATA_EXTS = {".json", ".csv", ".xml", ".xlsx"}
_DOC_EXTS = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".rtf",
             ".html", ".htm",
             ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"}
_ALL = _DATA_EXTS | _DOC_EXTS
_MAX_FILE = 50 * 1024 * 1024
_MAX_TOTAL = 500 * 1024 * 1024
_MAX_FILES = 50

_FK_REQUIRED_KEYS = frozenset({"source_type", "target_type", "source_attr", "target_attr"})
