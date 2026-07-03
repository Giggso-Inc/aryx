"""
Shortened URL model for in-platform link shortening.

Stores original URL, short code, and used_at to flag when the link was first clicked.
Optional thread_id, channel_id, entity_type, last_updated_at support targeted updates (e.g. on thread move).
"""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, Index
from sqlalchemy.sql import func

from app.core.database import Base
from app.core.db_types import UUID


class ShortenedUrl(Base):
    """Stores shortened URLs; used_at set when link is first clicked."""

    __tablename__ = "gg_shortened_urls"

    # Short code (e.g. 7-char) used in /redirect/{short_link}
    short_link = Column(String(7), primary_key=True, index=True)
    # Original long URL to redirect to
    original_url = Column(String(2048), nullable=False)
    # Set on first redirect (click); null until then
    used_at = Column(DateTime, nullable=True)
    # When the short link was created
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)

    # Optional columns for traceability and targeted updates (e.g. thread move)
    thread_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    channel_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    entity_type = Column(String(50), nullable=True)
    last_updated_at = Column(DateTime, nullable=True)

    __table_args__ = (Index("idx_shortened_url_used_at", "used_at"),)

    def __repr__(self):
        return f"<ShortenedUrl(short_link={self.short_link!r}, used_at={self.used_at})>"

