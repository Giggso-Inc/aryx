"""fix_is_connected_default_value

Revision ID: fix_is_connected_default_value
Revises: add_is_connected_to_datasource
Create Date: 2025-01-27 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fix_is_connected_default_value'
down_revision = 'add_is_connected_to_datasource'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Update existing records to set is_connected = true
    op.execute("UPDATE gg_datasources SET is_connected = true WHERE is_connected IS NULL OR is_connected = false")
    
    # Change the column default to true
    op.alter_column('gg_datasources', 'is_connected',
                    server_default='true',
                    existing_type=sa.Boolean(),
                    existing_nullable=False)


def downgrade() -> None:
    # Change the column default back to false
    op.alter_column('gg_datasources', 'is_connected',
                    server_default='false',
                    existing_type=sa.Boolean(),
                    existing_nullable=False)
