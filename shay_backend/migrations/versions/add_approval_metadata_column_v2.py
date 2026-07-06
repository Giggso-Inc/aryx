"""Add approval_metadata column to gg_approvals

Revision ID: add_approval_metadata_v2
Revises: 91b4b06b5ac9, update_task_due_date_datetime
Create Date: 2025-01-20 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_approval_metadata_v2'
down_revision = ('91b4b06b5ac9', 'update_task_due_date_datetime')
branch_labels = None
depends_on = None


def upgrade():
    # Add approval_metadata column to gg_approvals table
    op.add_column('gg_approvals', sa.Column('approval_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True, default={}))


def downgrade():
    # Remove approval_metadata column from gg_approvals table
    op.drop_column('gg_approvals', 'approval_metadata')
