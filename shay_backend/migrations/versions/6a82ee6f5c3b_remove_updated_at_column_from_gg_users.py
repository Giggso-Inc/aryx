"""remove_updated_at_column_from_gg_users

Revision ID: 6a82ee6f5c3b
Revises: add_approval_metadata_v2
Create Date: 2025-09-05 12:29:04.756994

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6a82ee6f5c3b'
down_revision = 'add_approval_metadata_v2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Remove the updated_at column from gg_users table.
    
    This column is redundant since we already have updated_datetime column
    which is properly defined in the User model.
    """
    # Get database connection and inspector to examine table structure
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    # Get list of all column names in the gg_users table
    columns = [col['name'] for col in inspector.get_columns('gg_users')]
    
    # Remove updated_at column only if it exists in the database
    if 'updated_at' in columns:
        op.drop_column('gg_users', 'updated_at')
        print("Dropped updated_at column from gg_users table")
    else:
        print("updated_at column does not exist in gg_users table, skipping")


def downgrade() -> None:
    """
    Re-add the updated_at column for rollback purposes.
    """
    # Get database connection and inspector to examine current table structure
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    # Get list of all column names in the gg_users table
    columns = [col['name'] for col in inspector.get_columns('gg_users')]
    
    # Re-add updated_at column only if it doesn't already exist
    if 'updated_at' not in columns:
        op.add_column('gg_users', sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')))
        print("Re-added updated_at column to gg_users table")
    else:
        print("updated_at column already exists in gg_users table, skipping") 