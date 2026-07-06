"""add_is_connected_to_datasource

Revision ID: add_is_connected_to_datasource
Revises: 86c6d78e1615
Create Date: 2025-01-27 10:00:000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_is_connected_to_datasource'
down_revision = '86c6d78e1615'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add is_connected column to gg_datasources table
    op.add_column('gg_datasources', sa.Column('is_connected', sa.Boolean(), nullable=False, server_default='true'))
    
    # Create index for the new column
    op.create_index('idx_datasource_is_connected', 'gg_datasources', ['is_connected'])


def downgrade() -> None:
    # Drop the index first
    op.drop_index('idx_datasource_is_connected', table_name='gg_datasources')
    
    # Drop the column
    op.drop_column('gg_datasources', 'is_connected')
