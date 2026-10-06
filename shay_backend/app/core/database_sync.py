"""
Synchronous SQLAlchemy engine factory for migrations.

Extracted from app/core/database.py: get_sync_engine() builds its own
fresh Engine per call and shares no state with the module-level async
engine/session factory in database.py, so it's a safe standalone
extraction — no behavior change.
"""

from urllib.parse import unquote

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database_url import _ensure_async_postgres_driver, _extract_oracle_dsn, _normalize_postgres_url


def build_sync_oracle_engine(*, pool_recycle: int | None = None) -> Engine:
    """Shared Oracle sync-engine construction, used by get_sync_engine()
    (migrations, no pool_recycle -- short-lived, one-off) and
    database.py's long-lived Oracle engine (pool_recycle set, matching the
    async engine config it replaces -- see docs/oci-oracle/
    ORACLE_THICK_MODE_MIGRATION_PLAN_2026-10-06.md "shay-api" section).
    Factored out so the JDBC-style/DSN URL handling lives in exactly one
    place rather than two copies drifting apart.
    """
    sync_oracle_url = (settings.DATABASE_URL or "").strip()
    if "oracledb_async" in sync_oracle_url.lower():
        sync_oracle_url = sync_oracle_url.replace("oracle+oracledb_async", "oracle+oracledb", 1)
    sync_oracle_url, oracle_dsn_sync = _extract_oracle_dsn(sync_oracle_url)
    sync_kw: dict = {
        "echo": settings.DEBUG,
        "pool_size": settings.DATABASE_POOL_SIZE,
        "max_overflow": settings.DATABASE_MAX_OVERFLOW,
        "pool_pre_ping": True,
    }
    if pool_recycle is not None:
        sync_kw["pool_recycle"] = pool_recycle
    if oracle_dsn_sync:
        sync_kw["connect_args"] = {"dsn": oracle_dsn_sync}
    return create_engine(sync_oracle_url, **sync_kw)


def get_sync_engine() -> Engine:
    """Get synchronous engine for migrations"""
    url = settings.DATABASE_URL or ""
    if url.startswith("sqlite"):
        return create_engine(
            url.replace("sqlite+aiosqlite", "sqlite"),
            echo=settings.DEBUG,
            connect_args={"check_same_thread": False}
        )
    elif url.strip().lower().startswith("oracle"):
        return build_sync_oracle_engine()
    else:
        # Use normalized URL for PostgreSQL (passwords with @, !, etc.).
        # Recomputes the same value database.py's module-level `_database_url`
        # holds (both are pure functions of settings.DATABASE_URL) rather than
        # importing it directly, to avoid a database.py <-> database_sync.py
        # import cycle (database.py re-exports get_sync_engine).
        _promoted = _ensure_async_postgres_driver(url)
        _promoted_lower = _promoted.strip().lower()
        pg_url = _normalize_postgres_url(_promoted) if _promoted_lower.startswith(("postgresql", "postgres")) else _promoted
        return create_engine(
            pg_url.replace("postgresql+asyncpg", "postgresql"),
            echo=settings.DEBUG,
            poolclass=StaticPool,
        )
