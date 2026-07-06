"""add_is_archived_to_channels

Revision ID: 176748bc1a11
Revises: 999c99b28d03
Create Date: 2025-08-28 18:22:00.246002

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '176748bc1a11'
down_revision = '999c99b28d03'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add is_archived column to gg_channels table
    op.add_column('gg_channels', sa.Column('is_archived', sa.Boolean(), nullable=False, server_default='false'))
    
    # Create index for better query performance on archived channels
    op.create_index('idx_channel_archived', 'gg_channels', ['is_archived'])


def downgrade() -> None:
    # Remove the index first
    op.drop_index('idx_channel_archived', 'gg_channels')
    
    # Remove the is_archived column
    op.drop_column('gg_channels', 'is_archived') 