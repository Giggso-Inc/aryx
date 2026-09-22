"""doc_discover_api.py duplicated file_ingest_api.py's original 50 MB
_MAX_FILE cap on its own /admin/docs/read endpoint -- same class of
problem (a real 223 MB MSI catalog export rejected), separate constant.
Raised in step with file_ingest_api.py's fix, first to 250 MB, then again
2026-09-11 to 500 MB (see test_doc_discover_size_limit_2026_09_11.py).
"""
from __future__ import annotations

from aryx.api.doc_discover import doc_discover_api as m


def test_max_file_covers_real_223mb_catalog_export() -> None:
    real_file_size = 223 * 1024 * 1024
    assert real_file_size < m._MAX_FILE
    assert m._MAX_FILE >= 250 * 1024 * 1024, "must never regress below this fix's original raise"
