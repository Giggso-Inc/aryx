"""
Database configuration and connection management
"""

import asyncio
from typing import AsyncGenerator
from urllib.parse import parse_qs, quote_plus, unquote, urlencode, urlparse, urlunparse
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import StaticPool

from app.core.config import settings


def _ensure_async_postgres_driver(url: str) -> str:
    """
    Normalize PostgreSQL URLs for async SQLAlchemy usage.

    Shay boot uses ``create_async_engine`` for PostgreSQL, so plain
    ``postgresql://`` (or psycopg2-flavoured) URLs must be promoted to
    ``postgresql+asyncpg://`` to avoid loading a synchronous driver.
    """
    if not url:
        return url

    raw = url.strip()
    lowered = raw.lower()
    if lowered.startswith("postgresql+asyncpg://"):
        return raw
    if lowered.startswith(("postgresql://", "postgres://", "postgresql+psycopg2://", "postgres+psycopg2://")):
        return f"postgresql+asyncpg://{raw.split('://', 1)[1]}"
    return raw


def _normalize_postgres_url(url: str) -> str:
    """
    Return a PostgreSQL URL safe for drivers: encode password so special chars (@, !, :, etc.) work.
    Leaves non-PostgreSQL and already-valid URLs unchanged. Only applied for postgresql/postgres schemes.
    """
    if not url or not url.strip().lower().startswith(("postgresql", "postgres+")):
        return url
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc or ""
        at_last = netloc.rfind("@")
        if at_last == -1:
            return url
        userinfo, hostport = netloc[:at_last], netloc[at_last + 1 :]
        colon_first = userinfo.find(":")
        if colon_first == -1:
            return url
        user, password = userinfo[:colon_first], userinfo[colon_first + 1 :]
        encoded_password = quote_plus(password, safe="")
        new_netloc = f"{user}:{encoded_password}@{hostport}"
        return urlunparse((parsed.scheme, new_netloc, parsed.path or "", parsed.params, parsed.query, parsed.fragment))
    except Exception:
        return url


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
    oracle_dsn = None
    if "//" in oracle_url and "@" in oracle_url:
        _after_slash = oracle_url.split("//", 1)[1]
        if "@" in _after_slash:
            _user_part, _host_part = _after_slash.split("@", 1)
            _host_stripped = _host_part.split("/")[0].split("?")[0].strip()
            if _host_stripped.startswith("(description"):
                # JDBC-style: TNS descriptor after @
                oracle_dsn = _host_stripped
                _scheme = oracle_url.split("//", 1)[0]
                oracle_url = f"{_scheme}//{_user_part}@localhost/"
            elif _host_stripped.startswith("%28description%3D") or _host_stripped.startswith("%28description%20%3D"):
                oracle_dsn = unquote(_host_stripped)
                _scheme = oracle_url.split("//", 1)[0]
                oracle_url = f"{_scheme}//{_user_part}@localhost/"
    if not oracle_dsn:
        parsed = urlparse(oracle_url)
        if parsed.query:
            qs = parse_qs(parsed.query, keep_blank_values=True)
            if "dsn" in qs and qs["dsn"]:
                oracle_dsn = qs["dsn"][0].strip()
                qs_clean = {k: v for k, v in qs.items() if k != "dsn"}
                new_query = urlencode(qs_clean, doseq=True)
                oracle_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
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


async def init_db():
    """Initialize database tables"""
    async with engine.begin() as conn:
        # Import all models to ensure they are registered
        from app.models import (
            User, Company, Workspace, Message, Thread, Attachment, AIResponse,
            Invitation, App, AppAccount, Channel, Task, Approval, Datasource, GiggsoVault,
            ChannelMember, Template, EmailVerificationToken, EmailNotifySettings,
            ShortenedUrl, SupportRequest,
        )

        # Create all tables
        await conn.run_sync(Base.metadata.create_all)

        # Create PostgreSQL-specific indexes and optimizations
        _url = settings.DATABASE_URL or ""
        if not _url.startswith("sqlite") and not _url.strip().lower().startswith("oracle"):
            await create_postgresql_optimizations(conn)

        print("✅ Database tables created successfully")


async def create_postgresql_optimizations(conn):
    """Create PostgreSQL-specific optimizations"""
    try:
        # Create hash indexes for UUID primary keys
        if settings.POSTGRES_USE_HASH_INDEXES:
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_hash ON gg_users USING HASH(id);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_companies_hash ON gg_company USING HASH(id);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_workspaces_hash ON gg_workspace USING HASH(id);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_hash ON gg_tasks USING HASH(id);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_approvals_hash ON gg_approvals USING HASH(id);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_datasources_hash ON gg_datasources USING HASH(id);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_channel_members_id_hash ON gg_channel_members USING HASH(id);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_gg_templates_id_hash ON gg_templates USING HASH(id);"
            )
        
        # Create composite indexes for common queries
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_thread_time ON gg_messages(thread_id, created_at);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_user_time ON gg_messages(user_id, created_at);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_ai_processed ON gg_messages(is_ai_processed, created_at);"
        )
        
        # Create indexes for company-based queries
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_company ON gg_users(company_id);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_workspaces_company ON gg_workspace(company_id);"
        )
        # Create indexes for workspace hierarchy
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_channels_workspace ON gg_channels(workspace_id);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_threads_channel ON gg_threads(channel_id);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_channel ON gg_messages(channel_id);"
        )
        
        # Create indexes for new models
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_status_time ON gg_tasks(status, created_at);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to ON gg_tasks(assigned_to, status);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_approvals_task_status ON gg_approvals(task_id, status);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_datasources_workspace ON gg_datasources(workspace_id);"
        )
        
        print("✅ PostgreSQL optimizations applied")
        
    except Exception as e:
        print(f"⚠️ Warning: Could not apply PostgreSQL optimizations: {e}")


async def close_db():
    """Close database connections"""
    await engine.dispose()


def get_sync_engine():
    """Get synchronous engine for migrations"""
    url = settings.DATABASE_URL or ""
    if url.startswith("sqlite"):
        return create_engine(
            url.replace("sqlite+aiosqlite", "sqlite"),
            echo=settings.DEBUG,
            connect_args={"check_same_thread": False}
        )
    elif url.strip().lower().startswith("oracle"):
        # Oracle: JDBC-style/DSN parsing; works with or without DSN (description=..., ?dsn=, or host:port/service)
        sync_oracle_url = settings.DATABASE_URL.strip()
        if "oracledb_async" in sync_oracle_url.lower():
            sync_oracle_url = sync_oracle_url.replace("oracle+oracledb_async", "oracle+oracledb", 1)
        oracle_dsn_sync = None
        if "//" in sync_oracle_url and "@" in sync_oracle_url:
            _after = sync_oracle_url.split("//", 1)[1]
            if "@" in _after:
                _user_part, _host_part = _after.split("@", 1)
                _host_stripped = _host_part.split("/")[0].split("?")[0].strip()
                if _host_stripped.startswith("(description"):
                    oracle_dsn_sync = _host_stripped
                    _scheme = sync_oracle_url.split("//", 1)[0]
                    sync_oracle_url = f"{_scheme}//{_user_part}@localhost/"
                elif _host_stripped.startswith("%28description%3D") or _host_stripped.startswith("%28description%20%3D"):
                    oracle_dsn_sync = unquote(_host_stripped)
                    _scheme = sync_oracle_url.split("//", 1)[0]
                    sync_oracle_url = f"{_scheme}//{_user_part}@localhost/"
        if not oracle_dsn_sync:
            parsed = urlparse(sync_oracle_url)
            if parsed.query:
                qs = parse_qs(parsed.query, keep_blank_values=True)
                if "dsn" in qs and qs["dsn"]:
                    oracle_dsn_sync = qs["dsn"][0].strip()
                    qs_clean = {k: v for k, v in qs.items() if k != "dsn"}
                    sync_oracle_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(qs_clean, doseq=True), parsed.fragment))
        sync_kw = {"echo": settings.DEBUG, "pool_size": settings.DATABASE_POOL_SIZE, "max_overflow": settings.DATABASE_MAX_OVERFLOW, "pool_pre_ping": True}
        if oracle_dsn_sync:
            sync_kw["connect_args"] = {"dsn": oracle_dsn_sync}
        return create_engine(sync_oracle_url, **sync_kw)
    else:
        # Use normalized URL for PostgreSQL (passwords with @, !, etc.)
        pg_url = _database_url if _db_url.startswith(("postgresql", "postgres")) else url
        return create_engine(
            pg_url.replace("postgresql+asyncpg", "postgresql"),
            echo=settings.DEBUG,
            poolclass=StaticPool,
        ) 
