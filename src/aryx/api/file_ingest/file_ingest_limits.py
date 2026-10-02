"""File-ingest size/type limits shared by the router and the ingest worker.

Split out of `api/file_ingest_api.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

_DATA_EXTS = {".json", ".csv", ".xml", ".xlsx"}

# CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md: layout-export
# uploads (native-UI JSON despite the historical ".txt" extension) route
# through cpq_ingestion.routing.cpq_layout_upload_active() into
# aryx_cpq_layout_file, never through the normal entity/CSV ingest path --
# ".json" was already in _DATA_EXTS above, only ".txt" needed adding.
_LAYOUT_EXTS = {".txt"}
_DOC_EXTS = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".rtf",
             ".html", ".htm",
             ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"}
_ALL = _DATA_EXTS | _DOC_EXTS | _LAYOUT_EXTS

# Live-confirmed (2026-09): a real MSI catalog export (aSTRO25_ConfigData.xml)
# is 223 MB. First raised from the original 50 MB/500 MB caps to 250 MB/750 MB
# for headroom around that file; raised again 2026-09-11 at the operator's
# request to 500 MB/1500 MB -- not sized to any specific hard ceiling.
# _MAX_TOTAL gives room for a couple of near-cap files in one batch.
_MAX_FILE = 500 * 1024 * 1024
_MAX_TOTAL = 1500 * 1024 * 1024
_MAX_FILES = 50

_FK_REQUIRED_KEYS = frozenset({"source_type", "target_type", "source_attr", "target_attr"})
