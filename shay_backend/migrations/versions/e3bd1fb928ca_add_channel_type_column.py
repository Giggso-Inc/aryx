"""add_channel_type_column

Revision ID: e3bd1fb928ca
Revises: 774dd7aa5d39
Create Date: 2025-10-23 13:10:24.975482

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e3bd1fb928ca'
down_revision = '774dd7aa5d39'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add channel_type column to gg_channels table
    op.add_column('gg_channels', sa.Column('channel_type', sa.Integer(), nullable=False, server_default='1'))


def downgrade() -> None:
    # Remove channel_type column from gg_channels table
    op.drop_column('gg_channels', 'channel_type') 