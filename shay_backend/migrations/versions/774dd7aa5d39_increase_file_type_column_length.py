"""increase_file_type_column_length

Revision ID: 774dd7aa5d39
Revises: 91b4b06b5ac9
Create Date: 2025-10-08 09:41:59.363103

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '774dd7aa5d39'
down_revision = '91b4b06b5ac9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Increase file_type column length from 50 to 255 characters
    op.alter_column('gg_datasources', 'file_type',
                    existing_type=sa.String(50),
                    type_=sa.String(255),
                    existing_nullable=True)


def downgrade() -> None:
    # Revert file_type column length back to 50 characters
    op.alter_column('gg_datasources', 'file_type',
                    existing_type=sa.String(255),
                    type_=sa.String(50),
                    existing_nullable=True) 