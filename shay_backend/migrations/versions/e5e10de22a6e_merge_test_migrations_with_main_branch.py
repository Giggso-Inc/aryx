"""merge test migrations with main branch

Revision ID: e5e10de22a6e
Revises: test_remove_column_from_users, create_only_project_tables
Create Date: 2025-08-14 10:58:50.235353

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5e10de22a6e'
down_revision = ('test_remove_column_from_users', 'create_only_project_tables')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass 