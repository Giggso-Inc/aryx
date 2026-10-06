"""
Database configuration and connection management

This file is imported by nearly every route file as `get_db`/`Base`/`engine`.
The block below that picks sqlite/oracle/postgres and calls
create_async_engine() runs ONCE at import time, building the live engine and
AsyncSessionLocal every other module binds to — that module-level
engine/session-factory lifecycle is kept in this single file on purpose
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md): splitting it further would
mean either making engine construction lazy (a behavior change — every
caller today gets an already-constructed engine at import time) or
introducing a second place that could re-run engine construction (risking
two live engines / duplicate connection pools). Both are real lifecycle
risks, not laziness, so it stays put.

What COULD be safely extracted without touching that lifecycle already has
been: URL-normalization helpers -> database_url.py, Oracle/Postgres
post-connect optimizations -> database_optimizations.py (both take a `conn`
parameter, no shared state), and the standalone get_sync_engine() migration
helper -> database_sync.py (builds its own independent Engine, shares no
state with the async engine here).
"""

import asyncio
import logging
from typing import AsyncGenerator
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.core.async_session_shim import make_async_session_local
from app.core.config import settings
from app.core.database_url import _ensure_async_postgres_driver, _normalize_postgres_url
from app.core.database_optimizations import (
    _oracle_repair_partial_unique_indexes,
    _oracle_repair_partial_unique_indexes_sync,
    create_postgresql_optimizations,
)
from app.core.database_sync import build_sync_oracle_engine, get_sync_engine  # noqa: F401 — get_sync_engine re-exported for external callers

logger = logging.getLogger(__name__)


def _set_oracle_call_timeout(dbapi_connection, _connection_record) -> None:
    """SQLAlchemy pool "connect" event: cap how long a single Oracle call
    may block before failing, so a stuck query releases its pool slot
    instead of holding it forever.

    docs/oci-oracle/SHAY_API_ORACLE_POOL_EXHAUSTION_PLAN_2026-09-14.md /
    SHAY_API_ORACLE_POOL_EXHAUSTION_INCIDENT_2026-09-30.md: without this,
    a query blocked server-side (a lock wait, a stuck session) holds its
    pool connection forever -- that's how the pool silently drains to
    zero over days. Mirrors the call_timeout pattern already used by
    Aryx's own Oracle pool (aryx/store/oracle_connection_pool.py). Fires
    on every new physical connection, not per-call, so it applies
    uniformly regardless of which route acquired the connection.
    """
    try:
        dbapi_connection.call_timeout = settings.DATABASE_ORACLE_CALL_TIMEOUT_MS
    except AttributeError:
        logger.warning(
            "database: oracledb connection has no call_timeout attribute "
            "-- skipping (driver version mismatch?)"
        )


__all__ = [
    "Base",
    "engine",
    "AsyncSessionLocal",
    "get_db",
    "init_db",
    "close_db",
    "get_sync_engine",
    "create_postgresql_optimizations",
    "_ensure_async_postgres_driver",
    "_normalize_postgres_url",
    "_oracle_repair_partial_unique_indexes",
    "_set_oracle_call_timeout",
]

_raw_database_url = settings.DATABASE_URL or ""
_database_url = _ensure_async_postgres_driver(_raw_database_url)
_db_url = _database_url.strip().lower()
# Use normalized URL for PostgreSQL so passwords with @, !, etc. work (sqlite/oracle unchanged)
_database_url = _normalize_postgres_url(_database_url) if _db_url.startswith(("postgresql", "postgres")) else _database_url
_is_oracle = _db_url.startswith("oracle")

if _db_url.startswith("sqlite"):
    # SQLite configuration
    engine = create_async_engine(
        _database_url,
        echo=settings.DEBUG,
        connect_args={"check_same_thread": False}
    )
elif _is_oracle:
    # Oracle DB: a plain SYNC engine, not create_async_engine -- see docs/
    # oci-oracle/ORACLE_THICK_MODE_MIGRATION_PLAN_2026-10-06.md "shay-api"
    # section. python-oracledb hardcodes thin mode for every asyncio
    # connection with no override (confirmed live: thick mode crash-looped
    # this service with DPY-2019 the moment an async connection was also
    # attempted in the same process -- driver_mode is a one-shot,
    # whole-process lock, not a per-connection setting). A sync engine is
    # the only way this service can use thick mode at all. AsyncSessionShim
    # (app/core/async_session_shim.py) keeps every `AsyncSessionLocal()` /
    # `Depends(get_db)` call site below working unchanged.
    engine = build_sync_oracle_engine(pool_recycle=settings.DATABASE_POOL_RECYCLE_SECONDS)
    event.listens_for(engine, "connect")(_set_oracle_call_timeout)
else:
    # PostgreSQL configuration with optimizations (use normalized URL for special chars in password)
    engine = create_async_engine(
        _database_url,
        echo=settings.DEBUG,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=settings.DATABASE_POOL_RECYCLE_SECONDS,
        connect_args={
            "server_settings": {
                "jit": "off",
                "random_page_cost": "1.1",
                "effective_cache_size": "256MB",
            }
        }
    )

# Create session factory. Oracle: AsyncSessionShim wraps a sync `Session`
# (see the Oracle branch above) behind the same callable/async-context-
# manager shape async_sessionmaker produces -- every `AsyncSessionLocal()`
# call site below and across the codebase keeps working unchanged.
if _is_oracle:
    AsyncSessionLocal = make_async_session_local(
        sessionmaker(bind=engine, expire_on_commit=False)
    )
else:
    AsyncSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False
    )

# Create base class for models
Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database tables"""
    import app.models  # noqa: F401 — importing the package registers all ORM classes with Base.metadata

    if _is_oracle:
        # engine is a sync Engine here (see the Oracle branch above) --
        # plain `with`/no `run_sync`/no `await`, not the async-engine path
        # below.
        with engine.begin() as conn:
            _oracle_repair_partial_unique_indexes_sync(conn)
            Base.metadata.create_all(conn)
        print("✅ Database tables created successfully")
        return

    async with engine.begin() as conn:
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)

        # Create PostgreSQL-specific indexes and optimizations
        if not _db_url.startswith("sqlite"):
            await create_postgresql_optimizations(conn)

        print("✅ Database tables created successfully")


async def close_db() -> None:
    """Close database connections"""
    if _is_oracle:
        # engine is a sync Engine here -- dispose() is not a coroutine on it.
        await asyncio.to_thread(engine.dispose)
        return
    await engine.dispose()
