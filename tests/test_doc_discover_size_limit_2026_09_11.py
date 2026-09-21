"""doc_discover_api.py duplicates file_ingest_api.py's _MAX_FILE cap on its
own /admin/docs/read endpoint. Raised in step with file_ingest_api.py's
2026-09-11 raise to 500 MB.
"""
from __future__ import annotations

from aryx.api.doc_discover import doc_discover_api as m


def test_max_file_raised_to_500mb() -> None:
    assert m._MAX_FILE == 500 * 1024 * 1024
    real_file_size = 223 * 1024 * 1024
    assert real_file_size < m._MAX_FILE
