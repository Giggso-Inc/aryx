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

# Live-confirmed (2026-09): a real MSI catalog export (aSTRO25_ConfigData.xml)
# is 223 MB -- raised from the original 50 MB/500 MB caps with headroom for
# that file plus room to grow, not sized to any specific hard ceiling.
_MAX_FILE = 250 * 1024 * 1024
_MAX_TOTAL = 750 * 1024 * 1024
_MAX_FILES = 50

_FK_REQUIRED_KEYS = frozenset({"source_type", "target_type", "source_attr", "target_attr"})
