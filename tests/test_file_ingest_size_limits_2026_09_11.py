"""file_ingest_api.py's caps were raised again 2026-09-11 at the operator's
request, from the 50 MB/500 MB pair (itself already a raise from the
original 2 MB/50 MB docstring-vs-constant drift) to 500 MB/1500 MB, to give
generous headroom above the known-real 223 MB MSI catalog export
(aSTRO25_ConfigData.xml) and room for multiple such files in one batch.
"""
from __future__ import annotations

from aryx.api.file_ingest import file_ingest_api as m


def test_constants_raised_to_500mb_per_file_1500mb_total() -> None:
    assert m._MAX_FILE == 500 * 1024 * 1024
    assert m._MAX_TOTAL == 1500 * 1024 * 1024


def test_per_file_limit_covers_known_real_223mb_file_with_room_to_grow() -> None:
    real_file_size = 223 * 1024 * 1024
    assert real_file_size < m._MAX_FILE
    # Headroom check: still room for the file to more than double.
    assert m._MAX_FILE > real_file_size * 2


def test_total_limit_allows_multiple_near_cap_files_in_one_batch() -> None:
    two_large_files = 2 * (m._MAX_FILE - 1)
    assert two_large_files < m._MAX_TOTAL


def test_status_endpoint_math_matches_raised_constants() -> None:
    # supported_types() (a nested closure inside file_ingest_router()) computes
    # max_file_mb/max_total_mb straight from these constants -- pinning the
    # arithmetic here catches drift without needing to spin up FastAPI.
    assert m._MAX_FILE // (1024 * 1024) == 500
    assert m._MAX_TOTAL // (1024 * 1024) == 1500
