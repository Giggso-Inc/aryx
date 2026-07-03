"""
GGDatasource model — unified datasource table supporting workspace, channel,
thread, and message scopes via the exclusive arc pattern.

Scope levels
────────────
  workspace  → datasource available to all channels/threads in the workspace
  channel    → datasource available to all threads in the channel
  thread     → datasource scoped to a specific thread
  message    → datasource attached to a specific message

Inheritance direction (read access): message > thread > channel > workspace
The most-specific scope wins when resolving which datasources an agent can see.
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


class GGDatasource(Base):
    """
    Unified datasource table.
    Exactly one of (workspace_id, channel_id, thread_id, message_id) must be
    set per row — enforced by a DB CHECK constraint and four partial unique
    indexes (one per scope level).
    """
    __tablename__ = "datasources"
    # -----------------------------------------------------------------------
    # Primary key
    # -----------------------------------------------------------------------
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, index=True)

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
    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("gg_messages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # -----------------------------------------------------------------------
    # Scope label — mirrors the FK that is set
    # -----------------------------------------------------------------------
    level = Column(String(20), nullable=False)  # workspace | channel | thread | message

    # -----------------------------------------------------------------------
    # Who added the datasource
    # -----------------------------------------------------------------------
    added_by = Column(
        UUID(as_uuid=True),
        ForeignKey("gg_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # -----------------------------------------------------------------------
    # Datasource identity
    # -----------------------------------------------------------------------
    name             = Column(String(255),  nullable=False, index=True)
    filename         = Column(String(500),  nullable=True)
    storage_type     = Column(String(50),   nullable=False)  # local | cloud | app
    provider         = Column(String(100),  nullable=True)   # s3, azure, googleDrive, sharePoint…
    app_type         = Column(String(100),  nullable=True)   # googleDrive, sharePoint…
    config           = Column(JSONB,        nullable=True, default={})
    datasource_metadata = Column(JSONB,     nullable=True, default={})

    # Vault reference — credentials are never stored in plaintext
    vault_unique_id  = Column(UUID(as_uuid=True), nullable=True)

    # -----------------------------------------------------------------------
    # File info
    # -----------------------------------------------------------------------
    file_size        = Column(Integer,      nullable=True)
    file_type        = Column(String(255),  nullable=True)
    file_url         = Column(String(1000), nullable=True)
    log_type         = Column(String(100),  nullable=True)  # android, kubernetes, python…

    # -----------------------------------------------------------------------
    # Status
    # -----------------------------------------------------------------------
    is_active        = Column(Boolean, nullable=False, default=True)
    is_connected     = Column(Boolean, nullable=False, default=True)
    is_processed     = Column(Boolean, nullable=False, default=False)
    processing_status = Column(String(50), nullable=False, default="pending")
    # pending | processing | completed | failed
    error_message    = Column(Text,    nullable=True)

    # -----------------------------------------------------------------------
    # Embedding
    # -----------------------------------------------------------------------
    is_embedding_required = Column(Boolean,  nullable=False, default=False)
    embedding_status      = Column(Integer,  nullable=False, default=0)
    # 0 = not required | 1 = in progress | 2 = completed | 3 = failed

    # -----------------------------------------------------------------------
    # Processing metadata
    # -----------------------------------------------------------------------
    last_processed_at = Column(DateTime, nullable=True)
    processing_time   = Column(Integer,  nullable=True)   # milliseconds
    record_count      = Column(Integer,  nullable=False, default=0)

    # -----------------------------------------------------------------------
    # Timestamps
    # -----------------------------------------------------------------------
    created_at = Column(DateTime, nullable=False, default=func.current_timestamp())
    updated_at = Column(
        DateTime,
        nullable=False,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------
    workspace = relationship("Workspace", backref="gg_datasources")
    channel   = relationship("Channel",   backref="gg_datasources")
    adder     = relationship("User",      foreign_keys=[added_by])

    # -----------------------------------------------------------------------
    # DB-level constraints
    # -----------------------------------------------------------------------
    __table_args__ = (
        # Exclusive arc: exactly one scope FK must be set and level must match
        CheckConstraint(
            "(level = 'workspace' AND workspace_id IS NOT NULL AND channel_id IS NULL  AND thread_id IS NULL  AND message_id IS NULL) OR "
            "(level = 'channel'   AND channel_id   IS NOT NULL AND workspace_id IS NULL AND thread_id IS NULL  AND message_id IS NULL) OR "
            "(level = 'thread'    AND thread_id    IS NOT NULL AND workspace_id IS NULL AND channel_id IS NULL AND message_id IS NULL) OR "
            "(level = 'message'   AND message_id   IS NOT NULL AND workspace_id IS NULL AND channel_id IS NULL AND thread_id IS NULL)",
            name="chk_gg_datasources_exclusive_arc",
        ),
        # Partial unique indexes: one datasource per (scope, name) per level
        Index("uk_gg_datasources_workspace", "workspace_id", "name",
              postgresql_where="level = 'workspace'", unique=True),
        Index("uk_gg_datasources_channel",   "channel_id",   "name",
              postgresql_where="level = 'channel'",   unique=True),
        Index("uk_gg_datasources_thread",    "thread_id",    "name",
              postgresql_where="level = 'thread'",    unique=True),
        Index("uk_gg_datasources_message",   "message_id",   "name",
              postgresql_where="level = 'message'",   unique=True),
        # Performance indexes
        Index("idx_gg_datasources_level",              "level"),
        Index("idx_gg_datasources_added_by",           "added_by"),
        Index("idx_gg_datasources_storage_type",       "storage_type"),
        Index("idx_gg_datasources_processing_status",  "processing_status"),
        Index("idx_gg_datasources_embedding_status",   "embedding_status"),
        Index("idx_gg_datasources_is_active",          "is_active"),
        {"extend_existing": True},
    )

    def __repr__(self):
        scope = self.workspace_id or self.channel_id or self.thread_id or self.message_id
        return f"<GGDatasource(id={self.id}, level={self.level}, scope={scope}, name={self.name!r})>"

    def to_dict(self):
        return {
            "id":                   str(self.id),
            "level":                self.level,
            "workspace_id":         str(self.workspace_id) if self.workspace_id else None,
            "channel_id":           str(self.channel_id)   if self.channel_id   else None,
            "thread_id":            str(self.thread_id)    if self.thread_id    else None,
            "message_id":           str(self.message_id)   if self.message_id   else None,
            "added_by":             str(self.added_by)     if self.added_by     else None,
            "name":                 self.name,
            "filename":             self.filename,
            "storage_type":         self.storage_type,
            "provider":             self.provider,
            "app_type":             self.app_type,
            "config":               self.config,
            "datasource_metadata":  self.datasource_metadata,
            "vault_unique_id":      str(self.vault_unique_id) if self.vault_unique_id else None,
            "file_size":            self.file_size,
            "file_type":            self.file_type,
            "file_url":             self.file_url,
            "log_type":             self.log_type,
            "is_active":            self.is_active,
            "is_connected":         self.is_connected,
            "is_processed":         self.is_processed,
            "processing_status":    self.processing_status,
            "error_message":        self.error_message,
            "is_embedding_required": self.is_embedding_required,
            "embedding_status":     self.embedding_status,
            "last_processed_at":    self.last_processed_at.isoformat() if self.last_processed_at else None,
            "processing_time":      self.processing_time,
            "record_count":         self.record_count,
            "created_at":           self.created_at.isoformat() if self.created_at else None,
            "updated_at":           self.updated_at.isoformat() if self.updated_at else None,
        }
