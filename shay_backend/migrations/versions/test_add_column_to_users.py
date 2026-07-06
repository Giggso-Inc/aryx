"""Test migration: Add test column to users table

Revision ID: test_add_column_to_users
Revises: 4816283117c2
Create Date: 2025-01-27 10:00:00.000000

This migration is for testing Alembic functionality in dev environment.
It adds a temporary test column that can be easily removed later.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'test_add_column_to_users'
down_revision = '4816283117c2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add test column to users table"""
    # Add a simple test column to verify migration works
    op.add_column('gg_users', sa.Column('test_column', sa.String(50), nullable=True))
    
    # Add a comment to document this is a test column
    op.execute("COMMENT ON COLUMN gg_users.test_column IS 'Temporary test column for migration testing'")


def downgrade() -> None:
    """Remove test column from users table"""
    # Remove the test column
    op.drop_column('gg_users', 'test_column')


