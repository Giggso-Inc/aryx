"""doc_discover_api.py duplicated file_ingest_api.py's original 50 MB
_MAX_FILE cap on its own /admin/docs/read endpoint -- same class of
problem (a real 223 MB MSI catalog export rejected), separate constant.
Raised in step with file_ingest_api.py's fix to 250 MB.
"""
from __future__ import annotations

from aryx.api.doc_discover import doc_discover_api as m


def test_max_file_raised_to_cover_real_223mb_catalog_export() -> None:
    assert m._MAX_FILE == 250 * 1024 * 1024
    real_file_size = 223 * 1024 * 1024
    assert real_file_size < m._MAX_FILE
