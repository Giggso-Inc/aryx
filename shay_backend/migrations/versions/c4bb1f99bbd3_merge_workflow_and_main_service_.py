"""merge workflow and main service migrations

Revision ID: c4bb1f99bbd3
Revises: 6a82ee6f5c3b, add_workflow_fields_to_tasks
Create Date: 2025-09-11 12:20:31.340797

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4bb1f99bbd3'
down_revision = ('6a82ee6f5c3b', 'add_workflow_fields_to_tasks')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass 