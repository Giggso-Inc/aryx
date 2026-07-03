"""Test migration: Remove test column from users table

Revision ID: test_remove_column_from_users
Revises: test_add_column_to_users
Create Date: 2025-01-27 10:00:00.000000

This migration removes the temporary test column that was added for testing.
This should be run after confirming that the migration system works correctly.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'test_remove_column_from_users'
down_revision = 'test_add_column_to_users'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Remove test column from users table"""
    # Remove the test column that was added for testing
    op.drop_column('gg_users', 'test_column')


def downgrade() -> None:
    """Re-add test column to users table (reverse of upgrade)"""
    # Re-add the test column (this would be used if we need to rollback)
    op.add_column('gg_users', sa.Column('test_column', sa.String(50), nullable=True))
    
    # Add the comment back
    op.execute("COMMENT ON COLUMN gg_users.test_column IS 'Temporary test column for migration testing'")


