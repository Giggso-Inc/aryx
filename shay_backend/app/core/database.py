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

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base

from app.core.config import settings
from app.core.database_url import _ensure_async_postgres_driver, _extract_oracle_dsn, _normalize_postgres_url
from app.core.database_optimizations import _oracle_repair_partial_unique_indexes, create_postgresql_optimizations
from app.core.database_sync import get_sync_engine  # noqa: F401 — re-exported for external callers

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
]

_raw_database_url = settings.DATABASE_URL or ""
_database_url = _ensure_async_postgres_driver(_raw_database_url)
_db_url = _database_url.strip().lower()
# Use normalized URL for PostgreSQL so passwords with @, !, etc. work (sqlite/oracle unchanged)
_database_url = _normalize_postgres_url(_database_url) if _db_url.startswith(("postgresql", "postgres")) else _database_url

if _db_url.startswith("sqlite"):
    # SQLite configuration
    engine = create_async_engine(
        _database_url,
        echo=settings.DEBUG,
        connect_args={"check_same_thread": False}
    )
elif _database_url.strip().lower().startswith("oracle"):
    # Oracle DB (new): JDBC-style or ?dsn= in DATABASE_URL; uses DATABASE_POOL_SIZE / DATABASE_MAX_OVERFLOW
    # Oracle DB: use oracledb_async so create_async_engine loads the async driver (required for asyncio)
    oracle_url = _database_url.strip()
    if "oracledb_async" not in oracle_url.lower():
        oracle_url = oracle_url.replace("oracle+oracledb", "oracle+oracledb_async", 1)
    # TCPS/SSL: DSN only from DATABASE_URL – JDBC-style @(description=...) or query ?dsn=...
    oracle_url, oracle_dsn = _extract_oracle_dsn(oracle_url)
    engine_kw: dict = {
        "echo": settings.DEBUG,
        "pool_size": settings.DATABASE_POOL_SIZE,
        "max_overflow": settings.DATABASE_MAX_OVERFLOW,
        "pool_pre_ping": True,
    }
    if oracle_dsn:
        engine_kw["connect_args"] = {"dsn": oracle_dsn}
    engine = create_async_engine(oracle_url, **engine_kw)
else:
    # PostgreSQL configuration with optimizations (use normalized URL for special chars in password)
    engine = create_async_engine(
        _database_url,
        echo=settings.DEBUG,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_pre_ping=True,
        connect_args={
            "server_settings": {
                "jit": "off",
                "random_page_cost": "1.1",
                "effective_cache_size": "256MB",
            }
        }
    )

# Create session factory
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
    async with engine.begin() as conn:
        import app.models  # noqa: F401 — importing the package registers all ORM classes with Base.metadata

        _url = settings.DATABASE_URL or ""
        if _url.strip().lower().startswith("oracle"):
            await _oracle_repair_partial_unique_indexes(conn)

        # Create all tables
        await conn.run_sync(Base.metadata.create_all)

        # Create PostgreSQL-specific indexes and optimizations
        if not _url.startswith("sqlite") and not _url.strip().lower().startswith("oracle"):
            await create_postgresql_optimizations(conn)

        print("✅ Database tables created successfully")


async def close_db() -> None:
    """Close database connections"""
    await engine.dispose()
