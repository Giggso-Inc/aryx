"""
GGMember model — unified membership for workspace / channel / thread scopes.
Replaces the old gg_channel_members table with an exclusive arc pattern.

Inheritance direction: bottom-up (thread > channel > workspace).
The most specific active role wins.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Index,
    String, UniqueConstraint, ForeignKey,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.db_types import UUID, JSONB
from app.core.database import Base


class GGMember(Base):
    """
    Unified membership table supporting workspace, channel, and thread scopes.

    Exactly one of (workspace_id, channel_id, thread_id) must be set —
    enforced by a DB CHECK constraint and three partial unique indexes.
    """

    __tablename__ = "gg_members"

    # -----------------------------------------------------------------------
    # Primary key
    # -----------------------------------------------------------------------
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, index=True)

    # -----------------------------------------------------------------------
    # Who is the member
    # -----------------------------------------------------------------------
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("gg_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # -----------------------------------------------------------------------
    # Exclusive arc — exactly one is set at the DB level
    # -----------------------------------------------------------------------
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("gg_workspace.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    channel_id = Column(
        UUID(as_uuid=True),
        ForeignKey("gg_channels.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    thread_id = Column(
        UUID(as_uuid=True),
        ForeignKey("gg_threads.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # -----------------------------------------------------------------------
    # Scope label — mirrors the FK that is set
    # -----------------------------------------------------------------------
    level = Column(String(20), nullable=False)  # workspace | channel | thread

    # -----------------------------------------------------------------------
    # Membership attributes
    # -----------------------------------------------------------------------
    role        = Column(String(50),  nullable=False, default="member")
    is_active   = Column(Boolean,     nullable=False, default=True)
    permissions = Column(JSONB,       nullable=True,  default={})
    invited_by  = Column(UUID(as_uuid=True), ForeignKey("gg_users.id", ondelete="SET NULL"), nullable=True)
    joined_at   = Column(DateTime, nullable=True)

    # -----------------------------------------------------------------------
    # Timestamps
    # -----------------------------------------------------------------------
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(
        DateTime,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------
    user       = relationship("User", foreign_keys=[user_id], backref="memberships")
    inviter    = relationship("User", foreign_keys=[invited_by])
    workspace  = relationship("Workspace", backref="members")
    channel    = relationship("Channel",   backref="members")

    # -----------------------------------------------------------------------
    # DB-level constraints
    # -----------------------------------------------------------------------
    __table_args__ = (
        # Exactly one scope FK must be set
        CheckConstraint(
            "(level = 'workspace' AND workspace_id IS NOT NULL AND channel_id IS NULL   AND thread_id IS NULL) OR "
            "(level = 'channel'   AND channel_id   IS NOT NULL AND workspace_id IS NULL AND thread_id IS NULL) OR "
            "(level = 'thread'    AND thread_id    IS NOT NULL AND workspace_id IS NULL AND channel_id IS NULL)",
            name="chk_gg_members_exclusive_arc",
        ),
        # Uniqueness per scope (partial indexes enforce one membership per user per scope)
        Index("uk_gg_members_workspace", "workspace_id", "user_id",
              postgresql_where="level = 'workspace'", unique=True),
        Index("uk_gg_members_channel",   "channel_id",   "user_id",
              postgresql_where="level = 'channel'",   unique=True),
        Index("uk_gg_members_thread",    "thread_id",    "user_id",
              postgresql_where="level = 'thread'",    unique=True),
        # Performance indexes
        Index("idx_gg_members_user_active", "user_id", "is_active"),
        Index("idx_gg_members_level",       "level"),
    )

    def __repr__(self) -> str:
        scope = self.workspace_id or self.channel_id or self.thread_id
        return f"<GGMember(id={self.id}, level={self.level}, scope={scope}, user={self.user_id}, role={self.role})>"

    def to_dict(self) -> dict:
        return {
            "id":           str(self.id),
            "user_id":      str(self.user_id),
            "level":        self.level,
            "workspace_id": str(self.workspace_id) if self.workspace_id else None,
            "channel_id":   str(self.channel_id)   if self.channel_id   else None,
            "thread_id":    str(self.thread_id)    if self.thread_id    else None,
            "role":         self.role,
            "is_active":    self.is_active,
            "permissions":  self.permissions,
            "invited_by":   str(self.invited_by) if self.invited_by else None,
            "joined_at":    self.joined_at.isoformat() if self.joined_at else None,
            "created_at":   self.created_at.isoformat() if self.created_at else None,
            "updated_at":   self.updated_at.isoformat() if self.updated_at else None,
        }
