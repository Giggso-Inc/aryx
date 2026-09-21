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
# is 223 MB. First raised from the original 50 MB/500 MB caps to 250 MB/750 MB
# for headroom around that file; raised again 2026-09-11 at the operator's
# request to 500 MB/1500 MB -- not sized to any specific hard ceiling.
# _MAX_TOTAL gives room for a couple of near-cap files in one batch.
_MAX_FILE = 500 * 1024 * 1024
_MAX_TOTAL = 1500 * 1024 * 1024
_MAX_FILES = 50

_FK_REQUIRED_KEYS = frozenset({"source_type", "target_type", "source_attr", "target_attr"})
