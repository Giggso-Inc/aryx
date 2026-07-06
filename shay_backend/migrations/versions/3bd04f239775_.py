"""empty message

Revision ID: 3bd04f239775
Revises: create_checklist_table, e5e10de22a6e, remove_duplicate_user_columns
Create Date: 2025-08-18 16:23:20.197584

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3bd04f239775'
down_revision = ('create_checklist_table', 'e5e10de22a6e', 'remove_duplicate_user_columns')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass 