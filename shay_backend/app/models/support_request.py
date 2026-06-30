"""
Support request model for user-initiated and tracked support tickets.

Stores name, email, description, optional subject/category, unique ticket reference,
timestamp, and optional source (e.g. "Support form", "API failure follow-up").
"""

from sqlalchemy import Column, String, DateTime, Text, Index, ForeignKey
from sqlalchemy.sql import func

from app.core.db_types import UUID
from app.core.database import Base


class SupportRequest(Base):
    """Support request model for customer support tracking."""

    __tablename__ = "gg_support_requests"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)

    # Company context (optional; when form is submitted from authenticated app context)
    company_id = Column(UUID(as_uuid=True), ForeignKey("gg_company.id"), nullable=True, index=True)
    company_name = Column(String(255), nullable=True)

    # User context (optional; logged-in user who submitted the request)
    user_id = Column(UUID(as_uuid=True), ForeignKey("gg_users.id"), nullable=True, index=True)

    # User-provided fields
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=False)

    # Optional subject/category (e.g. "Login", "Upload", "General")
    subject = Column(String(100), nullable=True, index=True)

    # Unique ticket reference for users and support to refer to (e.g. "SR-12345")
    ticket_reference = Column(String(50), unique=True, nullable=False, index=True)

    # When the request was created
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())

    # Optional source: "Support form", "API failure follow-up", etc.
    source = Column(String(100), nullable=True, default="Support form")

    __table_args__ = (
        Index("idx_support_requests_created_at", "created_at"),
        Index("idx_support_requests_email", "email"),
        Index("idx_support_requests_company_id", "company_id"),
        Index("idx_support_requests_user_id", "user_id"),
    )

    def __repr__(self):
        return f"<SupportRequest(id={self.id}, ticket_reference={self.ticket_reference}, email={self.email})>"
