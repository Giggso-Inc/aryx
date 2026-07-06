"""Regression tests for Shay database URL normalization."""

from app.core.database import _ensure_async_postgres_driver


def test_plain_postgres_url_is_promoted_to_asyncpg():
    url = "postgresql://aryx:secret@postgres:5432/aryx"
    assert _ensure_async_postgres_driver(url) == "postgresql+asyncpg://aryx:secret@postgres:5432/aryx"


def test_psycopg2_postgres_url_is_promoted_to_asyncpg():
    url = "postgresql+psycopg2://aryx:secret@postgres:5432/aryx"
    assert _ensure_async_postgres_driver(url) == "postgresql+asyncpg://aryx:secret@postgres:5432/aryx"


def test_asyncpg_url_is_left_unchanged():
    url = "postgresql+asyncpg://aryx:secret@postgres:5432/aryx"
    assert _ensure_async_postgres_driver(url) == url
