"""merge approval table with existing migrations

Revision ID: 6b3d995167ea
Revises: 6b80f51ea160, create_approval_table
Create Date: 2025-08-19 15:34:54.303013

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6b3d995167ea'
down_revision = ('6b80f51ea160', 'create_approval_table')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass 