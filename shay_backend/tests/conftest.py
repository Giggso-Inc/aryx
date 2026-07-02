"""
Pytest configuration and shared fixtures for shay-suite-backend tests.

Unit tests  : use mock_db (AsyncMock) — no real DB required.
Integration tests : use real_db — requires Docker test DB on TEST_DATABASE_URL.
  Start DB:  cd docker/test-db && docker compose -f docker-compose.test.yml --env-file .env.test up -d
  Set env:   export TEST_DATABASE_URL=postgresql+asyncpg://accsell_user:accsell_pass@localhost:5433/accsell_test
"""

import os
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Environment bootstrap — must happen before any app module is imported.
# Set DATABASE_URL so SQLAlchemy uses asyncpg instead of the aiosqlite default.
# Mock optional packages that may not be installed in the test environment.
# ---------------------------------------------------------------------------
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://accsell_user:accsell_pass@localhost:5433/accsell_test",
)
os.environ.setdefault(
    "SHAY_TOKEN_ENCRYPTION_KEY",
    "9a2b7c4d1e5f80316789a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abc",
)
os.environ.setdefault("ARYX_INTERNAL_API_KEY", "test-aryx-internal-key")
sys.modules.setdefault("socketio", MagicMock())
sys.modules.setdefault("python_socketio", MagicMock())

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

# ---------------------------------------------------------------------------
# Real-DB engine & session (integration tests only)
# ---------------------------------------------------------------------------
_TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://accsell_user:accsell_pass@localhost:5433/accsell_test",
)


@pytest.fixture(scope="session")
def test_engine():
    """Async SQLAlchemy engine pointed at the Docker test DB."""
    engine = create_async_engine(_TEST_DB_URL, echo=False, pool_pre_ping=True)
    yield engine
    asyncio.get_event_loop().run_until_complete(engine.dispose())


@pytest.fixture
def real_db(test_engine):
    """
    Async session connected to the Docker test DB.
    Each test runs inside a transaction that is rolled back on teardown,
    so tests are isolated and leave the DB clean.
    """
    async def _session():
        async with test_engine.connect() as conn:
            await conn.begin()
            session_factory = async_sessionmaker(
                bind=conn,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            async with session_factory() as session:
                yield session
            await conn.rollback()

    # Return a sync wrapper that pytest can iterate
    loop = asyncio.get_event_loop()
    gen = _session()
    session = loop.run_until_complete(gen.__anext__())
    yield session
    try:
        loop.run_until_complete(gen.__anext__())
    except StopAsyncIteration:
        pass


# ---------------------------------------------------------------------------
# App fixture — import app after path is set; skip lifespan to avoid real DB
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def app():
    with patch("app.core.migrations.run_migrations", new_callable=AsyncMock), \
         patch("app.core.socket.initialize_socket_service", new_callable=AsyncMock), \
         patch("app.services.daily_summary_scheduler.daily_summary_scheduler"):
        try:
            import main as main_module
            return main_module.app
        except Exception:
            from fastapi import FastAPI
            return FastAPI()


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# DB mock fixture
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_db():
    db = AsyncMock(spec=AsyncSession)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


# ---------------------------------------------------------------------------
# Auth user mocks
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_user():
    user = MagicMock()
    user.id = "user-admin-001"
    user.company_id = "company-001"
    user.role = "admin"
    user.email_id = "admin@example.com"
    user.name = "Admin User"
    user.avatar_url = None
    user.can_manage_workspace = MagicMock(return_value=True)
    return user


@pytest.fixture
def regular_user():
    user = MagicMock()
    user.id = "user-member-002"
    user.company_id = "company-001"
    user.role = "user"
    user.email_id = "member@example.com"
    user.name = "Regular User"
    user.avatar_url = None
    user.can_manage_workspace = MagicMock(return_value=False)
    return user


# ---------------------------------------------------------------------------
# Domain mocks
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_company():
    c = MagicMock()
    c.id = "company-001"
    c.name = "Test Company"
    c.domain = "example.com"
    c.subscription_plan = "pro"
    return c


@pytest.fixture
def mock_workspace():
    w = MagicMock()
    w.id = "workspace-001"
    w.name = "Test Workspace"
    w.company_id = "company-001"
    w.description = "A test workspace"
    w.is_public = True
    w.ai_enabled = False
    w.ai_provider = None
    w.ai_model = None
    w.settings = {}
    return w


@pytest.fixture
def mock_channel():
    ch = MagicMock()
    ch.id = "channel-001"
    ch.workspace_id = "workspace-001"
    ch.company_id = "company-001"
    ch.name = "general"
    ch.description = "General channel"
    ch.is_public = True
    return ch


@pytest.fixture
def mock_invitation():
    inv = MagicMock()
    inv.id = "inv-001"
    inv.email = "newuser@example.com"
    inv.role = "user"
    inv.company_id = "company-001"
    inv.invited_by = "user-admin-001"
    inv.status = "pending"
    inv.message = "Join us"
    inv.created_at = None
    inv.expires_at = None
    inv.is_valid = True
    return inv


@pytest.fixture
def mock_user():
    u = MagicMock()
    u.id = "user-001"
    u.name = "Test User"
    u.email_id = "test@example.com"
    u.role = "user"
    u.company_id = "company-001"
    u.avatar_url = None
    return u
