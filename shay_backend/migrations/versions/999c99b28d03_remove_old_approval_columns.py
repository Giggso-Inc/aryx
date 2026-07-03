"""Remove Old Approval Columns

This migration removes legacy columns that are no longer needed in the
approval system, cleaning up the table structure.

Revision ID: 999c99b28d03
Revises: b00f79d04a37
Create Date: 2025-08-19 16:17:38.763344

Author: Karthick Chandrasekar
Date: 19-08-2025
Version: 1.0.0

Purpose: Clean up legacy columns and finalize table structure
"""
# Alembic migration operations
from alembic import op
# SQLAlchemy for database schema operations
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '999c99b28d03'
down_revision = 'b00f79d04a37'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if table exists
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()
    
    if 'gg_approvals' not in existing_tables:
        print("Table 'gg_approvals' does not exist, skipping cleanup")
        return
    
    existing_columns = [col['name'] for col in inspector.get_columns('gg_approvals')]
    print(f"Existing columns before cleanup: {existing_columns}")
    
    # Remove old columns that are no longer needed
    old_columns = ['requested_by', 'approved_by', 'comments', 'approval_date']
    
    for col_name in old_columns:
        if col_name in existing_columns:
            op.drop_column('gg_approvals', col_name)
            print(f"Removed old column: {col_name}")
    
    print("Cleanup completed")


def downgrade() -> None:
    # Check if table exists
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()
    
    if 'gg_approvals' not in existing_tables:
        return
    
    existing_columns = [col['name'] for col in inspector.get_columns('gg_approvals')]
    
    # Re-add old columns if they don't exist
    if 'requested_by' not in existing_columns:
        op.add_column('gg_approvals', sa.Column('requested_by', sa.String(length=36), nullable=True))
    if 'approved_by' not in existing_columns:
        op.add_column('gg_approvals', sa.Column('approved_by', sa.String(length=36), nullable=True))
    if 'comments' not in existing_columns:
        op.add_column('gg_approvals', sa.Column('comments', sa.Text(), nullable=True))
    if 'approval_date' not in existing_columns:
        op.add_column('gg_approvals', sa.Column('approval_date', sa.DateTime(), nullable=True)) 