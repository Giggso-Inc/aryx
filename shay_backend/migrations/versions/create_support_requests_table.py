"""Create gg_support_requests table for customer support requests

Revision ID: create_support_requests
Revises: 6a82ee6f5c3b
Create Date: 2025-03-03

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "create_support_requests"
down_revision = "6a82ee6f5c3b"
branch_labels = None
depends_on = None


def upgrade():
    # Create support requests table (base); company_id, company_name, user_id added in later migrations
    op.create_table(
        "gg_support_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(length=100), nullable=True),
        sa.Column("ticket_reference", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_support_requests_created_at", "gg_support_requests", ["created_at"])
    op.create_index("idx_support_requests_email", "gg_support_requests", ["email"])
    op.create_index("idx_support_requests_ticket_reference", "gg_support_requests", ["ticket_reference"], unique=True)
    op.create_index("idx_support_requests_subject", "gg_support_requests", ["subject"])


def downgrade():
    op.drop_table("gg_support_requests")
