"""
Remove duplicate columns from gg_users table

This migration safely removes duplicate timestamp columns (created_at, updated_at) 
from the gg_users table while preserving the is_active column and the correct 
timestamp columns (created_datetime, updated_datetime).

Author: Karthick Chandrasekar
Date: 2025-08-14
Version: 1.0.0

Revision ID: remove_duplicate_user_columns
Revises: ecbda37a5c80
Create Date: 2025-01-20 15:30:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'remove_duplicate_user_columns'
down_revision = 'ecbda37a5c80'
branch_labels = None
depends_on = None


def upgrade():
    """
    Remove duplicate timestamp columns from gg_users table.
    
    This function safely removes the duplicate created_at and updated_at columns
    while preserving the correct timestamp columns (created_datetime, updated_datetime).
    It first inspects the database schema to ensure columns exist before attempting
    to drop them, preventing errors if the schema is different than expected.
    """
    
    # Get database connection and inspector to examine table structure
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    # Get list of all column names in the gg_users table
    columns = [col['name'] for col in inspector.get_columns('gg_users')]
    
    # Note: We're not dropping is_active since user confirmed only one exists in DB
    # This prevents accidentally removing the correct is_active column
    if 'is_active' in columns:
        # Check if there are multiple is_active columns (this would be unusual)
        # For now, let's not drop is_active since you mentioned only one exists
        pass
    
    # Safely remove created_at column only if it exists in the database
    if 'created_at' in columns:
        op.drop_column('gg_users', 'created_at')
        print("Dropped created_at column")
    else:
        print("created_at column does not exist, skipping")
    
    # Safely remove updated_at column only if it exists in the database
    if 'updated_at' in columns:
        op.drop_column('gg_users', 'updated_at')
        print("Dropped updated_at column")
    else:
        print("updated_at column does not exist, skipping")


def downgrade():
    """
    Re-add the removed timestamp columns for rollback purposes.
    
    This function safely re-adds the created_at and updated_at columns that were
    removed in the upgrade function. It checks if the columns already exist before
    adding them to prevent duplicate column errors during rollback operations.
    """
    
    # Get database connection and inspector to examine current table structure
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    # Get list of all column names in the gg_users table
    columns = [col['name'] for col in inspector.get_columns('gg_users')]
    
    # Re-add created_at column only if it doesn't already exist
    if 'created_at' not in columns:
        op.add_column('gg_users', sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')))
        print("Re-added created_at column")
    else:
        print("created_at column already exists, skipping")
    
    # Re-add updated_at column only if it doesn't already exist
    if 'updated_at' not in columns:
        op.add_column('gg_users', sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')))
        print("Re-added updated_at column")
    else:
        print("updated_at column already exists, skipping")
