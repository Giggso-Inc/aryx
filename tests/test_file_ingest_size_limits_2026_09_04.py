"""Live-confirmed gap (2026-09): a real MSI catalog export
(aSTRO25_ConfigData.xml, 223 MB) was rejected by the /admin/ingest/file
endpoint's _MAX_FILE cap, which was still set to the original 50 MB.
_MAX_FILE/_MAX_TOTAL raised to 250 MB/750 MB with headroom for that file
plus room to grow. The status endpoint and error messages now derive
their reported limits from the constants themselves (max_file_mb =
_MAX_FILE // (1024*1024)) instead of separate hardcoded literals, so
they can never drift out of sync with the real limit again the way the
module docstring already had (it said "2 MB/50 MB" while the constants
were 50 MB/500 MB).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile


def _mock_file(filename: str, size_bytes: int) -> UploadFile:
    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = filename
    mock_file.read = AsyncMock(return_value=b"x" * size_bytes)
    return mock_file


def _get_handler():
    from aryx.api.file_ingest.file_ingest_api import file_ingest_router
    router = file_ingest_router()
    return next(r for r in router.routes if "POST" in r.methods).endpoint


def test_constants_raised_to_cover_real_223mb_catalog_export() -> None:
    from aryx.api.file_ingest import file_ingest_api as m
    assert m._MAX_FILE == 250 * 1024 * 1024
    assert m._MAX_TOTAL == 750 * 1024 * 1024
    real_file_size = 223 * 1024 * 1024
    assert real_file_size < m._MAX_FILE, "the file that triggered this fix must now fit"


def test_status_endpoint_reports_the_real_current_limits() -> None:
    from aryx.api.file_ingest.file_ingest_api import file_ingest_router
    router = file_ingest_router()
    status_fn = next(
        r for r in router.routes if r.path == "/admin/ingest/supported"
    ).endpoint
    result = status_fn()
    assert result["max_file_mb"] == 250
    assert result["max_total_mb"] == 750


def test_file_under_new_limit_is_accepted(monkeypatch) -> None:
    """Regression guard: a file between the old (50 MB) and new (250 MB)
    cap -- exactly the shape of file this fix exists for -- must not be
    rejected."""
    mock_future = MagicMock()
    mock_executor = MagicMock()
    mock_executor.submit.return_value = mock_future
    mock_file = _mock_file("aSTRO25_ConfigData.xml", 100 * 1024 * 1024)

    with patch("aryx.api.file_ingest.file_ingest_api._get_executor", return_value=mock_executor), \
         patch("aryx.api.file_ingest.file_ingest_api.get_settings") as mock_cfg, \
         patch("aryx.api.file_ingest.file_ingest_api.JobStore"):
        mock_cfg.return_value.rdb_dsn = "postgresql://x"
        mock_cfg.return_value.effective_worker_backend.return_value = "local"
        handler = _get_handler()
        result = asyncio.run(handler(
            files=[mock_file], ontology_type="Company",
            match_keys="name", fk_links="[]", workspace_id=1,
        ))

    assert result["status"] == "queued"
    mock_future.add_done_callback.assert_called_once()


def test_file_over_new_limit_still_rejected_with_accurate_message() -> None:
    """A file genuinely over the new 250 MB cap must still be rejected --
    this fix raises the ceiling, it doesn't remove it -- and the error
    message must report the real current limit, not a stale literal."""
    mock_file = _mock_file("huge.xml", 260 * 1024 * 1024)

    with patch("aryx.api.file_ingest.file_ingest_api.get_settings") as mock_cfg:
        mock_cfg.return_value.rdb_dsn = "postgresql://x"
        handler = _get_handler()
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(handler(
                files=[mock_file], ontology_type="Company",
                match_keys="name", fk_links="[]", workspace_id=1,
            ))

    assert exc_info.value.status_code == 400
    assert "250 MB" in exc_info.value.detail
    assert "huge.xml" in exc_info.value.detail
