"""
Dialect-aware database types for PostgreSQL and Oracle compatibility.

When DATABASE_URL is PostgreSQL, these types resolve to the same native types
(UUID, JSONB, ARRAY) as before, so Postgres behavior is unchanged.
When DATABASE_URL is Oracle, they map to Oracle-compatible types.
"""

import uuid
from sqlalchemy import TypeDecorator, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB as PG_JSONB, ARRAY as PG_ARRAY


# ---------------------------------------------------------------------------
# UUID: native UUID on PostgreSQL, CHAR(36) on Oracle
# ---------------------------------------------------------------------------
class DialectUUID(TypeDecorator):
    """UUID that maps to PostgreSQL UUID or Oracle VARCHAR2(36). Accepts as_uuid for drop-in."""

    impl = String(36)
    cache_ok = True

    def __init__(self, as_uuid=True, **kw):
        super().__init__(**kw)
        self.as_uuid = as_uuid

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return str(value) if not isinstance(value, str) else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        try:
            return uuid.UUID(value) if isinstance(value, str) else value
        except (TypeError, ValueError):
            return value


# ---------------------------------------------------------------------------
# JSON: JSONB on PostgreSQL, JSON/CLOB on Oracle
# ---------------------------------------------------------------------------
class DialectJSON(TypeDecorator):
    """JSON that maps to PostgreSQL JSONB or Oracle JSON/CLOB."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_JSONB())
        if dialect.name == "oracle":
            try:
                from sqlalchemy.dialects.oracle import JSON
                return dialect.type_descriptor(JSON())
            except Exception:
                return dialect.type_descriptor(Text())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        return value

    def process_result_value(self, value, dialect):
        return value


# ---------------------------------------------------------------------------
# UUID array: ARRAY(UUID) on PostgreSQL, JSON array on Oracle
# ---------------------------------------------------------------------------
class DialectUUIDArray(TypeDecorator):
    """Array of UUIDs: PostgreSQL ARRAY(UUID), Oracle stored as JSON."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_ARRAY(PG_UUID(as_uuid=True)))
        if dialect.name == "oracle":
            try:
                from sqlalchemy.dialects.oracle import JSON
                return dialect.type_descriptor(JSON())
            except Exception:
                return dialect.type_descriptor(Text())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        # Oracle: store as list of UUID strings
        if isinstance(value, list):
            return [str(v) for v in value]
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        if isinstance(value, list):
            return [uuid.UUID(str(v)) if v else None for v in value]
        return value


# Drop-in aliases so models can keep similar names; use these in imports
# to avoid touching every column name (only change import source).
UUID = DialectUUID
JSONB = DialectJSON
