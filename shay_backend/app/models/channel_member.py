"""
ChannelMember model for per-user access control to channels
"""

from sqlalchemy import Column, String, DateTime, Boolean, Index, UniqueConstraint, ForeignKey
from app.core.db_types import UUID, JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class ChannelMember(Base):
    """Membership mapping of users to channels within a company."""

    __tablename__ = "gg_channel_members"

    # Primary key - native UUID for PostgreSQL
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)

    # Foreign keys / associations
    channel_id = Column(UUID(as_uuid=True), ForeignKey("gg_channels.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("gg_users.id"), nullable=False, index=True)

    # Membership attributes
    role = Column(String(50), nullable=False, default="member")  # admin, member, viewer, etc.
    is_active = Column(Boolean, nullable=False, default=True)
    permissions = Column(JSONB, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(
        DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False
    )

    # PostgreSQL-specific indexes and constraints
    __table_args__ = (
        # Ensure a user can only have one membership per channel
        UniqueConstraint("channel_id", "user_id", name="uq_channel_user_membership"),
        # Helpful composite index for lookups
        Index("idx_channel_user", "channel_id", "user_id"),
        Index("idx_members_role", "role"),
        # Hash index on id for fast equality (PostgreSQL only)
        Index("idx_channel_members_id_hash", "id"),
    )

    def __repr__(self) -> str:
        return f"<ChannelMember(id={self.id}, channel_id={self.channel_id}, user_id={self.user_id}, role={self.role})>"


