"""empty message

Revision ID: 6b80f51ea160
Revises: 3bd04f239775, add_created_by_to_tasks
Create Date: 2025-08-18 18:15:54.194077

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6b80f51ea160'
down_revision = ('3bd04f239775', 'add_created_by_to_tasks')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass 