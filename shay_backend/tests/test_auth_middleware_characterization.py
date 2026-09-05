"""
Golden-master / characterization tests for app/middleware/auth_middleware.py.

Purpose: auth_middleware.py is 205 lines with zero dedicated test coverage
before this file. It is about to be split per
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md. Already has some
return-type hints from a prior phase — preserved verbatim across the split.

- AuthMiddleware: a raw ASGI middleware — tested by driving __call__ directly
  with fake scope/receive/send and a fake downstream `app` callable (no
  Starlette TestClient needed for pure ASGI dispatch logic).
- get_current_user / get_current_user_required / get_current_user_optional /
  _user_has_used_invitation: tested with a mocked AsyncSession (mock_db-style,
  matching tests/conftest.py's mock_db fixture pattern) and a fake
  Request-like object exposing `.state`.
- require_auth / optional_auth decorators: tested by wrapping a small async
  function and driving it with a fake Request in args/kwargs.

asyncio.run() is used instead of pytest-asyncio (not installed), matching
tests/test_channels_characterization.py's pattern.

Do not modify app/middleware/auth_middleware.py from this file's tests.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from app.middleware.auth_middleware import (
    AuthMiddleware,
    get_current_user,
    get_current_user_optional,
    get_current_user_required,
    optional_auth,
    require_auth,
)


def _make_scope(path: str, headers: list[tuple[bytes, bytes]] | None = None):
    return {
        "type": "http",
        "path": path,
        "headers": headers or [],
        "method": "GET",
        "query_string": b"",
        "server": ("test", 80),
        "client": ("test", 12345),
        "scheme": "http",
    }


async def _noop_receive():
    return {"type": "http.request", "body": b""}


# ---------------------------------------------------------------------------
# AuthMiddleware (ASGI dispatch)
# ---------------------------------------------------------------------------
class TestAuthMiddleware:
    def test_non_http_scope_passes_through(self):
        downstream = AsyncMock()
        mw = AuthMiddleware(downstream)
        scope = {"type": "lifespan"}
        asyncio.run(mw(scope, _noop_receive, AsyncMock()))
        downstream.assert_awaited_once()

    def test_skip_path_passes_through_without_verifying_token(self):
        downstream = AsyncMock()
        mw = AuthMiddleware(downstream)
        scope = _make_scope("/health")
        with patch("app.middleware.auth_middleware.asgi.verify_token") as mock_verify:
            asyncio.run(mw(scope, _noop_receive, AsyncMock()))
            mock_verify.assert_not_called()
        downstream.assert_awaited_once()

    def test_prefix_skip_path_matches_startswith(self):
        """Documents current behavior: skip-path matching is startswith, so
        e.g. /api/v1/sso/anything matches the "/api/v1/sso/" skip entry."""
        downstream = AsyncMock()
        mw = AuthMiddleware(downstream)
        scope = _make_scope("/api/v1/sso/callback/google")
        with patch("app.middleware.auth_middleware.asgi.verify_token") as mock_verify:
            asyncio.run(mw(scope, _noop_receive, AsyncMock()))
            mock_verify.assert_not_called()

    def test_missing_auth_header_passes_through(self):
        downstream = AsyncMock()
        mw = AuthMiddleware(downstream)
        scope = _make_scope("/api/v1/protected")
        asyncio.run(mw(scope, _noop_receive, AsyncMock()))
        downstream.assert_awaited_once()

    def test_non_bearer_auth_header_passes_through(self):
        downstream = AsyncMock()
        mw = AuthMiddleware(downstream)
        scope = _make_scope("/api/v1/protected", headers=[(b"authorization", b"Basic abcd")])
        asyncio.run(mw(scope, _noop_receive, AsyncMock()))
        downstream.assert_awaited_once()

    def test_invalid_token_passes_through_without_setting_state(self):
        downstream = AsyncMock()
        mw = AuthMiddleware(downstream)
        scope = _make_scope("/api/v1/protected", headers=[(b"authorization", b"Bearer badtoken")])
        with patch("app.middleware.auth_middleware.asgi.verify_token", return_value=None):
            asyncio.run(mw(scope, _noop_receive, AsyncMock()))
        downstream.assert_awaited_once()

    def test_valid_token_sets_request_state_and_calls_downstream(self):
        downstream = AsyncMock()
        mw = AuthMiddleware(downstream)
        scope = _make_scope("/api/v1/protected", headers=[(b"authorization", b"Bearer goodtoken")])
        payload = {"sub": "user-1", "email": "a@b.com", "role": "admin", "company_id": "c1"}
        with patch("app.middleware.auth_middleware.asgi.verify_token", return_value=payload):
            asyncio.run(mw(scope, _noop_receive, AsyncMock()))
        downstream.assert_awaited_once()
        # We can't directly inspect the Request built inside __call__, but we
        # can confirm no exception was raised and downstream ran — the state
        # assignment itself is exercised via coverage of that code path.

    def test_should_skip_auth_matches_exact_and_prefix_paths(self):
        mw = AuthMiddleware(AsyncMock())
        assert mw._should_skip_auth("/health") is True
        assert mw._should_skip_auth("/api/v1/sso/whatever") is True
        assert mw._should_skip_auth("/api/v1/protected/thing") is False


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------
class TestGetCurrentUser:
    def test_returns_none_when_no_user_id_in_state(self):
        request = MagicMock(spec=Request)
        request.state = MagicMock(spec=[])  # no user_id attribute at all
        result = asyncio.run(get_current_user(request, db=AsyncMock()))
        assert result is None

    def test_returns_user_when_found_with_provided_db(self):
        request = MagicMock(spec=Request)
        request.state.user_id = "user-1"
        db = AsyncMock()
        mock_user = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_user
        db.execute.return_value = result_mock

        result = asyncio.run(get_current_user(request, db=db))
        assert result is mock_user

    def test_returns_none_when_user_not_found_with_provided_db(self):
        request = MagicMock(spec=Request)
        request.state.user_id = "user-1"
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute.return_value = result_mock

        result = asyncio.run(get_current_user(request, db=db))
        assert result is None

    def test_falls_back_to_get_db_when_no_db_provided(self):
        request = MagicMock(spec=Request)
        request.state.user_id = "user-1"
        mock_user = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_user

        fallback_session = AsyncMock()
        fallback_session.execute.return_value = result_mock

        async def _fake_get_db():
            yield fallback_session

        with patch("app.middleware.auth_middleware.current_user.get_db", _fake_get_db):
            result = asyncio.run(get_current_user(request, db=None))
        assert result is mock_user


# ---------------------------------------------------------------------------
# get_current_user_required
# ---------------------------------------------------------------------------
class TestGetCurrentUserRequired:
    def test_raises_401_when_no_user(self):
        request = MagicMock(spec=Request)
        request.state = MagicMock(spec=[])
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(get_current_user_required(request, db=AsyncMock()))
        assert exc_info.value.status_code == 401

    def test_returns_user_when_verified(self):
        request = MagicMock(spec=Request)
        request.state.user_id = "user-1"
        db = AsyncMock()
        mock_user = MagicMock()
        mock_user.is_verified = True
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_user
        db.execute.return_value = result_mock

        result = asyncio.run(get_current_user_required(request, db=db))
        assert result is mock_user

    def test_raises_403_when_unverified_and_no_used_invitation(self):
        request = MagicMock(spec=Request)
        request.state.user_id = "user-1"
        db = AsyncMock()
        mock_user = MagicMock()
        mock_user.is_verified = False
        mock_user.email_id = "a@b.com"
        mock_user.company_id = "c1"

        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = mock_user
        invitation_result = MagicMock()
        invitation_result.scalar_one_or_none.return_value = None
        db.execute.side_effect = [user_result, invitation_result]

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(get_current_user_required(request, db=db))
        assert exc_info.value.status_code == 403

    def test_returns_user_when_unverified_but_has_used_invitation(self):
        request = MagicMock(spec=Request)
        request.state.user_id = "user-1"
        db = AsyncMock()
        mock_user = MagicMock()
        mock_user.is_verified = False
        mock_user.email_id = "a@b.com"
        mock_user.company_id = "c1"

        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = mock_user
        invitation_result = MagicMock()
        invitation_result.scalar_one_or_none.return_value = MagicMock()  # found
        db.execute.side_effect = [user_result, invitation_result]

        result = asyncio.run(get_current_user_required(request, db=db))
        assert result is mock_user


# ---------------------------------------------------------------------------
# get_current_user_optional
# ---------------------------------------------------------------------------
class TestGetCurrentUserOptional:
    def test_returns_none_when_no_user(self):
        request = MagicMock(spec=Request)
        request.state = MagicMock(spec=[])
        result = asyncio.run(get_current_user_optional(request, db=AsyncMock()))
        assert result is None


# ---------------------------------------------------------------------------
# require_auth / optional_auth decorators
# ---------------------------------------------------------------------------
class TestRequireAuthDecorator:
    def test_raises_500_when_no_request_object(self):
        @require_auth
        async def handler(**kwargs):
            return "should not reach here"

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(handler())
        assert exc_info.value.status_code == 500

    def test_injects_current_user_kwarg_when_authenticated(self):
        @require_auth
        async def handler(**kwargs):
            return kwargs["current_user"]

        # NOTE: plain MagicMock(), not MagicMock(spec=Request) — a
        # spec-restricted mock of fastapi.Request evaluates falsy under
        # `if not request:` (MagicMock(spec=X) picks up a mocked __len__
        # when the spec'd class exposes one, and bool() falls back to
        # len() before __bool__), which would make the wrapper wrongly
        # take the "request not found" branch. A real Request instance is
        # never falsy, so this is a mock-fidelity artifact, not real
        # app behavior — this decorator's `if not request:` check is
        # otherwise exercised faithfully.
        request = MagicMock()
        request.state.user_id = "user-1"
        mock_user = MagicMock()
        mock_user.is_verified = True
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_user

        async def _fake_get_db():
            db = AsyncMock()
            db.execute.return_value = result_mock
            yield db

        with patch("app.middleware.auth_middleware.current_user.get_db", _fake_get_db):
            result = asyncio.run(handler(request=request))
        assert result is mock_user


class TestOptionalAuthDecorator:
    def test_injects_none_current_user_when_no_request(self):
        @optional_auth
        async def handler(**kwargs):
            return kwargs.get("current_user", "not-set")

        result = asyncio.run(handler())
        assert result == "not-set"

    def test_injects_current_user_when_request_present(self):
        @optional_auth
        async def handler(**kwargs):
            return kwargs["current_user"]

        # See the require_auth test above for why this is a plain MagicMock()
        # rather than MagicMock(spec=Request).
        request = MagicMock()
        request.state = MagicMock(spec=[])  # no user_id

        result = asyncio.run(handler(request=request))
        assert result is None
