"""
Golden-master / characterization tests for app/core/database.py.

Purpose: database.py is 345 lines with zero dedicated test coverage before
this file (tests/test_database_url_normalization.py only covers
_ensure_async_postgres_driver). It is about to be split per
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md. database.py is imported by
nearly every route file as `get_db`, and the module-level engine/session
factory is created at import time from settings.DATABASE_URL — that part is
inherently hard to unit test in isolation (re-importing the module per test
case is unreliable and risks masking real behavior), so per the task's
explicit guidance these tests focus on the module's standalone helper
functions instead:

- _normalize_postgres_url (password URL-encoding for postgres URLs)
- get_db (the async session dependency generator's error/close handling)
- _oracle_repair_partial_unique_indexes (Oracle partial-unique-index repair)
- create_postgresql_optimizations (Postgres index creation, with the
  settings.POSTGRES_USE_HASH_INDEXES flag)

asyncio.run() is used instead of pytest-asyncio (not installed), matching
tests/test_channels_characterization.py's pattern. All async helpers are
exercised against mocked connections/sessions — no real DB required.

Do not modify app/core/database.py from this file's tests.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.database import (
    _normalize_postgres_url,
    _oracle_repair_partial_unique_indexes,
    _set_oracle_call_timeout,
    create_postgresql_optimizations,
    get_db,
)
from app.core.database_url import _extract_oracle_dsn


# ---------------------------------------------------------------------------
# _normalize_postgres_url
# ---------------------------------------------------------------------------
class TestNormalizePostgresUrl:
    def test_encodes_special_chars_in_password(self):
        url = "postgresql+asyncpg://user:p@ss!w:ord@host:5432/db"
        result = _normalize_postgres_url(url)
        # rfind("@") picks the LAST '@' as the userinfo/hostport split point.
        assert result == "postgresql+asyncpg://user:p%40ss%21w%3Aord@host:5432/db"

    def test_non_postgres_scheme_returned_unchanged(self):
        url = "sqlite+aiosqlite:///./test.db"
        assert _normalize_postgres_url(url) == url

    def test_empty_url_returned_unchanged(self):
        assert _normalize_postgres_url("") == ""

    def test_no_at_sign_returned_unchanged(self):
        url = "postgresql://host:5432/db"
        assert _normalize_postgres_url(url) == url

    def test_no_colon_in_userinfo_returned_unchanged(self):
        # userinfo present (has '@') but no ':' separating user/password.
        url = "postgresql://user@host:5432/db"
        assert _normalize_postgres_url(url) == url

    def test_postgres_plus_scheme_is_recognized(self):
        # Guard clause checks startswith(("postgresql", "postgres+")) — a bare
        # "postgres://" (no '+') does NOT match "postgresql" nor "postgres+",
        # so it is returned unchanged. This documents that pre-existing quirk.
        url = "postgres://user:pa:ss@host:5432/db"
        assert _normalize_postgres_url(url) == url

    def test_malformed_url_falls_back_to_original_on_exception(self):
        # urlparse doesn't raise on most garbage input, so to hit the except
        # branch we patch urlparse to raise directly. NOTE: _normalize_postgres_url
        # lives in app.core.database_url (post-split) — patch must target that
        # module, not app.core.database (which only re-imports the name).
        with patch("app.core.database_url.urlparse", side_effect=ValueError("boom")):
            url = "postgresql://user:pass@host:5432/db"
            assert _normalize_postgres_url(url) == url

    def test_preserves_path_and_query(self):
        url = "postgresql://user:p@ss@host:5432/dbname?sslmode=require"
        result = _normalize_postgres_url(url)
        assert result == "postgresql://user:p%40ss@host:5432/dbname?sslmode=require"


# ---------------------------------------------------------------------------
# get_db
# ---------------------------------------------------------------------------
class TestGetDb:
    def test_yields_session_and_closes_it(self):
        mock_session = AsyncMock()

        class _CtxMgr:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *a):
                return False

        with patch("app.core.database.AsyncSessionLocal", return_value=_CtxMgr()):
            async def _drive():
                gen = get_db()
                session = await gen.__anext__()
                assert session is mock_session
                with pytest.raises(StopAsyncIteration):
                    await gen.__anext__()

            asyncio.run(_drive())
        mock_session.close.assert_awaited_once()

    def test_session_closed_even_if_consumer_raises(self):
        """The finally block runs session.close() even when the generator is
        closed early via an exception thrown into it (documents current
        try/finally behavior, not a bug)."""
        mock_session = AsyncMock()

        class _CtxMgr:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *a):
                return False

        with patch("app.core.database.AsyncSessionLocal", return_value=_CtxMgr()):
            async def _drive():
                gen = get_db()
                await gen.__anext__()
                with pytest.raises(RuntimeError):
                    await gen.athrow(RuntimeError("consumer failed"))

            asyncio.run(_drive())
        mock_session.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# _oracle_repair_partial_unique_indexes
# ---------------------------------------------------------------------------
class TestOracleRepairPartialUniqueIndexes:
    def test_repairs_indexes_reported_as_unique(self):
        conn = AsyncMock()

        select_result = MagicMock()
        select_result.fetchone.return_value = ("UNIQUE",)

        async def _execute(stmt, *args, **kwargs):
            text_str = str(stmt)
            if "user_indexes" in text_str:
                return select_result
            return MagicMock()

        conn.execute.side_effect = _execute

        asyncio.run(_oracle_repair_partial_unique_indexes(conn))

        # 10 arc indexes: 1 SELECT + 1 DROP + 1 CREATE each = 30 calls.
        assert conn.execute.await_count == 30

    def test_noop_when_index_already_non_unique(self):
        conn = AsyncMock()
        select_result = MagicMock()
        select_result.fetchone.return_value = ("NONUNIQUE",)
        conn.execute.return_value = select_result

        asyncio.run(_oracle_repair_partial_unique_indexes(conn))

        # Only the 10 SELECTs run; no DROP/CREATE.
        assert conn.execute.await_count == 10

    def test_noop_when_index_row_missing(self):
        conn = AsyncMock()
        select_result = MagicMock()
        select_result.fetchone.return_value = None
        conn.execute.return_value = select_result

        asyncio.run(_oracle_repair_partial_unique_indexes(conn))

        assert conn.execute.await_count == 10

    def test_swallows_exception_from_drop_or_create(self):
        """DROP/CREATE failures are caught and logged, not raised — the
        repair continues to the next index."""
        conn = AsyncMock()
        select_result = MagicMock()
        select_result.fetchone.return_value = ("UNIQUE",)

        call_count = {"n": 0}

        async def _execute(stmt, *args, **kwargs):
            text_str = str(stmt)
            if "user_indexes" in text_str:
                return select_result
            call_count["n"] += 1
            if "DROP INDEX" in text_str:
                raise Exception("ORA-00001: cannot drop")
            return MagicMock()

        conn.execute.side_effect = _execute

        # Should not raise despite the DROP INDEX failure on every index.
        asyncio.run(_oracle_repair_partial_unique_indexes(conn))


# ---------------------------------------------------------------------------
# create_postgresql_optimizations
# ---------------------------------------------------------------------------
class TestCreatePostgresqlOptimizations:
    def test_creates_hash_indexes_when_flag_enabled(self):
        conn = AsyncMock()
        # NOTE: create_postgresql_optimizations lives in
        # app.core.database_optimizations (post-split) and imports `settings`
        # itself there — patch must target that module.
        with patch("app.core.database_optimizations.settings") as mock_settings:
            mock_settings.POSTGRES_USE_HASH_INDEXES = True
            asyncio.run(create_postgresql_optimizations(conn))

        calls = [str(c.args[0]) for c in conn.execute.await_args_list]
        assert any("idx_users_hash" in c for c in calls)
        assert any("idx_messages_thread_time" in c for c in calls)
        # 8 hash indexes + 12 other indexes = 20 total.
        assert conn.execute.await_count == 20

    def test_skips_hash_indexes_when_flag_disabled(self):
        conn = AsyncMock()
        with patch("app.core.database_optimizations.settings") as mock_settings:
            mock_settings.POSTGRES_USE_HASH_INDEXES = False
            asyncio.run(create_postgresql_optimizations(conn))

        calls = [str(c.args[0]) for c in conn.execute.await_args_list]
        assert not any("HASH" in c for c in calls)
        assert conn.execute.await_count == 12

    def test_swallows_exception_and_does_not_raise(self):
        conn = AsyncMock()
        conn.execute.side_effect = Exception("connection lost")
        with patch("app.core.database_optimizations.settings") as mock_settings:
            mock_settings.POSTGRES_USE_HASH_INDEXES = True
            # Should not raise.
            asyncio.run(create_postgresql_optimizations(conn))


# ---------------------------------------------------------------------------
# _extract_oracle_dsn — extracted (post-split) from duplicated inline logic
# previously in database.py's engine-creation block and get_sync_engine().
# ---------------------------------------------------------------------------
class TestExtractOracleDsn:
    def test_jdbc_style_description_dsn(self):
        url = "oracle+oracledb_async://user@(description=(address=(host=h)(port=1521)))/svc"
        clean_url, dsn = _extract_oracle_dsn(url)
        assert dsn == "(description=(address=(host=h)(port=1521)))"
        assert clean_url == "oracle+oracledb_async://user@localhost/"

    def test_url_encoded_description_dsn(self):
        url = "oracle+oracledb_async://user@%28description%3D%28address%3D%28host%3Dh%29%29%29/"
        clean_url, dsn = _extract_oracle_dsn(url)
        assert dsn == "(description=(address=(host=h)))"
        assert clean_url == "oracle+oracledb_async://user@localhost/"

    def test_query_string_dsn(self):
        url = "oracle+oracledb_async://user@host/?dsn=mydb_high&foo=bar"
        clean_url, dsn = _extract_oracle_dsn(url)
        assert dsn == "mydb_high"
        assert clean_url == "oracle+oracledb_async://user@host/?foo=bar"

    def test_query_string_dsn_no_other_params(self):
        url = "oracle+oracledb_async://user@host/?dsn=mydb_high"
        clean_url, dsn = _extract_oracle_dsn(url)
        assert dsn == "mydb_high"
        assert clean_url == "oracle+oracledb_async://user@host/"

    def test_plain_host_no_dsn(self):
        url = "oracle+oracledb_async://user:pw@host:1521/service"
        clean_url, dsn = _extract_oracle_dsn(url)
        assert dsn is None
        assert clean_url == url


# ---------------------------------------------------------------------------
# _set_oracle_call_timeout -- docs/oci-oracle/SHAY_API_ORACLE_POOL_
# EXHAUSTION_PLAN_2026-09-14.md / SHAY_API_ORACLE_POOL_EXHAUSTION_
# INCIDENT_2026-09-30.md fix: caps how long a single Oracle call may
# block, so a stuck query releases its pool slot instead of holding it
# forever and silently draining the pool.
# ---------------------------------------------------------------------------
class TestSetOracleCallTimeout:
    def test_sets_call_timeout_from_settings(self):
        dbapi_connection = MagicMock()
        with patch("app.core.database.settings") as mock_settings:
            mock_settings.DATABASE_ORACLE_CALL_TIMEOUT_MS = 60000
            _set_oracle_call_timeout(dbapi_connection, MagicMock())
        assert dbapi_connection.call_timeout == 60000

    def test_logs_warning_instead_of_raising_when_attribute_unsupported(self):
        class _NoCallTimeout:
            def __setattr__(self, name, value):
                if name == "call_timeout":
                    raise AttributeError("call_timeout not supported")
                super().__setattr__(name, value)

        # Should not raise despite the driver not supporting call_timeout.
        _set_oracle_call_timeout(_NoCallTimeout(), MagicMock())
