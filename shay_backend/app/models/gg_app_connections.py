"""
GGAppConnection model — unified app connections supporting workspace / channel / thread scopes.

Stored in the separate 'gg_app_connections' table (exclusive arc pattern).
This is a new table — the existing gg_app_accounts table is left untouched.

Scope levels
────────────
  workspace  → app connection available to all channels/threads in the workspace
  channel    → app connection scoped to a specific channel
  thread     → app connection scoped to a specific thread

Inheritance direction: thread > channel > workspace (most specific wins).
"""

from uuid import uuid4

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Index,
    Integer, String, Text, ForeignKey,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.db_types import UUID, JSONB
from app.core.database import Base


class GGAppConnection(Base):
    """
    Unified app-connection table (gg_app_connections) supporting workspace,
    channel, and thread scopes.

    Exactly one of (workspace_id, channel_id, thread_id) must be set per row —
    enforced by a DB CHECK constraint and three partial unique indexes.
    """

    __tablename__ = "gg_app_connections"

    # -----------------------------------------------------------------------
    # Primary key
    # -----------------------------------------------------------------------
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, index=True)

    # -----------------------------------------------------------------------
    # Which app
    # -----------------------------------------------------------------------
    app_id = Column(
        UUID(as_uuid=True),
        ForeignKey("gg_apps.id", ondelete="SET NULL"),
        nullable=True,
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
    level = Column(String(20), nullable=False, default="workspace")  # workspace | channel | thread

    # -----------------------------------------------------------------------
    # Who connected the app
    # -----------------------------------------------------------------------
    connected_by = Column(
        UUID(as_uuid=True),
        ForeignKey("gg_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # -----------------------------------------------------------------------
    # Connection metadata
    # -----------------------------------------------------------------------
    connection_name     = Column(String(255), nullable=True)
    connection_status   = Column(String(50),  nullable=False, default="active")
    connection_settings = Column(JSONB,       nullable=True,  default={})
    api_key             = Column(String(500),  nullable=True)
    webhook_url         = Column(String(500),  nullable=True)
    callback_url        = Column(String(500),  nullable=True)
    last_sync_at        = Column(DateTime,     nullable=True)
    sync_status         = Column(String(50),   nullable=True)
    error_message       = Column(Text,         nullable=True)
    is_active           = Column(Boolean,      nullable=False, default=True)
    auto_sync           = Column(Boolean,      nullable=False, default=False)
    sync_interval       = Column(Integer,      nullable=False, default=3600)

    # Provider / OAuth fields
    provider            = Column(String(50),  nullable=True)
    provider_account_id = Column(String(255), nullable=True)
    auth_type           = Column(String(50),  nullable=True, default="oauth2")
    provider_metadata   = Column(JSONB,       nullable=True, default={})
    last_token_refresh  = Column(DateTime,    nullable=True)
    token_expires_at    = Column(DateTime,    nullable=True)

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
    app       = relationship("App",       backref="gg_app_connections")
    connector = relationship("User",      foreign_keys=[connected_by], backref="gg_app_connections")
    workspace = relationship("Workspace", backref="gg_app_connections")
    channel   = relationship("Channel",   backref="gg_app_connections")

    # -----------------------------------------------------------------------
    # DB-level constraints
    # -----------------------------------------------------------------------
    __table_args__ = (
        CheckConstraint(
            "(level = 'workspace' AND workspace_id IS NOT NULL AND channel_id IS NULL   AND thread_id IS NULL) OR "
            "(level = 'channel'   AND channel_id   IS NOT NULL AND workspace_id IS NULL AND thread_id IS NULL) OR "
            "(level = 'thread'    AND thread_id    IS NOT NULL AND workspace_id IS NULL AND channel_id IS NULL)",
            name="chk_gg_app_connections_exclusive_arc",
        ),
        # Partial unique indexes: one app connection per (scope FK, app_id) per level
        Index("uk_gg_app_connections_workspace", "workspace_id", "app_id",
              postgresql_where="level = 'workspace'", unique=True),
        Index("uk_gg_app_connections_channel",   "channel_id",   "app_id",
              postgresql_where="level = 'channel'",   unique=True),
        Index("uk_gg_app_connections_thread",    "thread_id",    "app_id",
              postgresql_where="level = 'thread'",    unique=True),
        # Performance indexes
        Index("idx_gg_app_connections_status_time",   "connection_status", "created_at"),
        Index("idx_gg_app_connections_sync_status",   "sync_status",       "last_sync_at"),
        Index("idx_gg_app_connections_active_sync",   "is_active",         "auto_sync"),
        Index("idx_gg_app_connections_connected_by",  "connected_by",      "created_at"),
        Index("idx_gg_app_connections_level",         "level"),
    )

    def __repr__(self):
        scope = self.workspace_id or self.channel_id or self.thread_id
        return f"<GGAppConnection(id={self.id}, level={self.level}, scope={scope}, app={self.app_id})>"

    def to_dict(self):
        return {
            "id":                  str(self.id),
            "app_id":              str(self.app_id) if self.app_id else None,
            "level":               self.level,
            "workspace_id":        str(self.workspace_id) if self.workspace_id else None,
            "channel_id":          str(self.channel_id)   if self.channel_id   else None,
            "thread_id":           str(self.thread_id)    if self.thread_id    else None,
            "connected_by":        str(self.connected_by),
            "connection_name":     self.connection_name,
            "connection_status":   self.connection_status,
            "connection_settings": self.connection_settings,
            "webhook_url":         self.webhook_url,
            "callback_url":        self.callback_url,
            "last_sync_at":        self.last_sync_at.isoformat()       if self.last_sync_at       else None,
            "sync_status":         self.sync_status,
            "error_message":       self.error_message,
            "is_active":           self.is_active,
            "auto_sync":           self.auto_sync,
            "sync_interval":       self.sync_interval,
            "provider":            self.provider,
            "provider_account_id": self.provider_account_id,
            "auth_type":           self.auth_type,
            "provider_metadata":   self.provider_metadata,
            "last_token_refresh":  self.last_token_refresh.isoformat()  if self.last_token_refresh  else None,
            "token_expires_at":    self.token_expires_at.isoformat()    if self.token_expires_at    else None,
            "created_at":          self.created_at.isoformat()          if self.created_at           else None,
            "updated_at":          self.updated_at.isoformat()          if self.updated_at           else None,
        }
