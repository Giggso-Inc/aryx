"""add_created_by_updated_by_to_company_and_channel

Revision ID: eff5d16184fb
Revises: e3bd1fb928ca
Create Date: 2025-10-29 11:19:28.482727

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'eff5d16184fb'
down_revision = 'e3bd1fb928ca'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add created_by and updated_by columns to gg_company table
    op.add_column('gg_company', sa.Column('created_by', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('gg_company', sa.Column('updated_by', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
    
    # Add created_by and updated_by columns to gg_channels table
    op.add_column('gg_channels', sa.Column('created_by', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('gg_channels', sa.Column('updated_by', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    # Remove created_by and updated_by columns from gg_channels table
    op.drop_column('gg_channels', 'updated_by')
    op.drop_column('gg_channels', 'created_by')
    
    # Remove created_by and updated_by columns from gg_company table
    op.drop_column('gg_company', 'updated_by')
    op.drop_column('gg_company', 'created_by') 