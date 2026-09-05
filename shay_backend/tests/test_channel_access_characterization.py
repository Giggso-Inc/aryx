"""
Golden-master / characterization tests for app/utils/channel_access.py.

Purpose: channel_access.py is 183 lines with zero dedicated test coverage
before this file. It is about to be split per
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.

Both functions are exercised with a mocked AsyncSession (mock_db-style,
matching tests/conftest.py's mock_db fixture pattern) — no real DB.

asyncio.run() is used instead of pytest-asyncio (not installed), matching
tests/test_channels_characterization.py's pattern.

Do not modify app/utils/channel_access.py from this file's tests.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.utils.channel_access import check_channel_access, check_channel_access_by_thread

CHANNEL_ID = str(uuid.uuid4())
THREAD_ID = str(uuid.uuid4())


def _make_db(results: list):
    """Builds a mock AsyncSession whose .execute() returns each result_mock
    in `results`, in order, one per call."""
    db = AsyncMock()
    db.execute.side_effect = results
    return db


def _result(scalar_value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar_value
    return r


# ---------------------------------------------------------------------------
# check_channel_access
# ---------------------------------------------------------------------------
class TestCheckChannelAccess:
    def test_invalid_channel_id_raises_400(self):
        db = AsyncMock()
        user = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(check_channel_access(db, user, "not-a-uuid"))
        assert exc_info.value.status_code == 400

    def test_invalid_channel_id_returns_false_when_not_raising(self):
        db = AsyncMock()
        user = MagicMock()
        result = asyncio.run(check_channel_access(db, user, "not-a-uuid", raise_on_denied=False))
        assert result is False

    def test_channel_not_found_raises_404(self):
        db = _make_db([_result(None)])
        user = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(check_channel_access(db, user, CHANNEL_ID))
        assert exc_info.value.status_code == 404

    def test_channel_not_found_returns_false_when_not_raising(self):
        db = _make_db([_result(None)])
        user = MagicMock()
        result = asyncio.run(check_channel_access(db, user, CHANNEL_ID, raise_on_denied=False))
        assert result is False

    def test_active_member_grants_access(self):
        mock_channel = MagicMock()
        mock_member = MagicMock()
        db = _make_db([_result(mock_channel), _result(mock_member)])
        user = MagicMock()
        result = asyncio.run(check_channel_access(db, user, CHANNEL_ID))
        assert result is True

    def test_non_member_raises_403(self):
        mock_channel = MagicMock()
        db = _make_db([_result(mock_channel), _result(None)])
        user = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(check_channel_access(db, user, CHANNEL_ID))
        assert exc_info.value.status_code == 403

    def test_non_member_returns_false_when_not_raising(self):
        mock_channel = MagicMock()
        db = _make_db([_result(mock_channel), _result(None)])
        user = MagicMock()
        result = asyncio.run(check_channel_access(db, user, CHANNEL_ID, raise_on_denied=False))
        assert result is False


# ---------------------------------------------------------------------------
# check_channel_access_by_thread
# ---------------------------------------------------------------------------
class TestCheckChannelAccessByThread:
    def test_invalid_thread_id_raises_400(self):
        db = AsyncMock()
        user = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(check_channel_access_by_thread(db, user, "not-a-uuid"))
        assert exc_info.value.status_code == 400

    def test_invalid_thread_id_returns_none_when_not_raising(self):
        db = AsyncMock()
        user = MagicMock()
        result = asyncio.run(check_channel_access_by_thread(db, user, "not-a-uuid", raise_on_denied=False))
        assert result is None

    def test_thread_not_found_raises_404(self):
        db = _make_db([_result(None)])
        user = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(check_channel_access_by_thread(db, user, THREAD_ID))
        assert exc_info.value.status_code == 404

    def test_thread_not_found_returns_none_when_not_raising(self):
        db = _make_db([_result(None)])
        user = MagicMock()
        result = asyncio.run(check_channel_access_by_thread(db, user, THREAD_ID, raise_on_denied=False))
        assert result is None

    def test_has_access_returns_channel_id(self):
        thread_channel_id = uuid.uuid4()
        mock_thread = MagicMock()
        mock_thread.channel_id = thread_channel_id
        mock_channel = MagicMock()
        mock_member = MagicMock()
        # 1st execute: thread lookup, 2nd: channel lookup (inside
        # check_channel_access), 3rd: membership lookup.
        db = _make_db([_result(mock_thread), _result(mock_channel), _result(mock_member)])
        user = MagicMock()
        result = asyncio.run(check_channel_access_by_thread(db, user, THREAD_ID))
        assert result == str(thread_channel_id)

    def test_no_access_returns_none_when_not_raising(self):
        thread_channel_id = uuid.uuid4()
        mock_thread = MagicMock()
        mock_thread.channel_id = thread_channel_id
        mock_channel = MagicMock()
        db = _make_db([_result(mock_thread), _result(mock_channel), _result(None)])
        user = MagicMock()
        result = asyncio.run(check_channel_access_by_thread(db, user, THREAD_ID, raise_on_denied=False))
        assert result is None

    def test_no_access_raises_403_when_raising(self):
        thread_channel_id = uuid.uuid4()
        mock_thread = MagicMock()
        mock_thread.channel_id = thread_channel_id
        mock_channel = MagicMock()
        db = _make_db([_result(mock_thread), _result(mock_channel), _result(None)])
        user = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(check_channel_access_by_thread(db, user, THREAD_ID))
        assert exc_info.value.status_code == 403
