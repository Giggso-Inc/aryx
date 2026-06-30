"""add_embedding_columns_to_datasources

Revision ID: add_embedding_columns
Revises: 4816283117c2
Create Date: 2025-01-27 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_embedding_columns'
down_revision = '4816283117c2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add is_embedding_required column to gg_datasources table
    op.add_column('gg_datasources', sa.Column('is_embedding_required', sa.Boolean(), nullable=False, server_default='false'))
    
    # Add embedding_status column to gg_datasources table
    # 0 = not required, 1 = in progress, 2 = completed, 3 = failed
    op.add_column('gg_datasources', sa.Column('embedding_status', sa.Integer(), nullable=False, server_default='0'))
    
    # Create index for the embedding_status column for efficient querying
    op.create_index('idx_datasource_embedding_status', 'gg_datasources', ['embedding_status'])


def downgrade() -> None:
    # Drop the index first
    op.drop_index('idx_datasource_embedding_status', table_name='gg_datasources')
    
    # Drop the columns
    op.drop_column('gg_datasources', 'embedding_status')
    op.drop_column('gg_datasources', 'is_embedding_required')


