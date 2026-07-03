"""Fix Approval Table Column Names

This migration renames old column names to new standardized names and adds
missing columns to ensure the approval table structure is consistent.

Revision ID: b00f79d04a37
Revises: 2d80b4405b2a
Create Date: 2025-08-19 16:16:30.612209

Author: Karthick Chandrasekar
Date: 19-08-2025
Version: 1.0.0

Purpose: Standardize column names and add missing columns
"""
# Alembic migration operations
from alembic import op
# SQLAlchemy for database schema operations
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b00f79d04a37'
down_revision = '2d80b4405b2a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if table exists
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()
    
    if 'gg_approvals' not in existing_tables:
        print("Table 'gg_approvals' does not exist, skipping column fixes")
        return
    
    existing_columns = [col['name'] for col in inspector.get_columns('gg_approvals')]
    print(f"Existing columns: {existing_columns}")
    
    # Fix column names if they exist
    if 'requested_by' in existing_columns and 'requested_by_user_id' not in existing_columns:
        # Rename requested_by to requested_by_user_id
        op.alter_column('gg_approvals', 'requested_by', new_column_name='requested_by_user_id')
        print("Renamed column: requested_by -> requested_by_user_id")
    
    if 'approver' in existing_columns and 'approver_user_id' not in existing_columns:
        # Rename approver to approver_user_id
        op.alter_column('gg_approvals', 'approver', new_column_name='approver_user_id')
        print("Renamed column: approver -> approver_user_id")
    
    # Add missing columns if they don't exist
    if 'thread_id' not in existing_columns:
        op.add_column('gg_approvals', sa.Column('thread_id', sa.String(length=36), nullable=True))
        print("Added column: thread_id")
    
    if 'message_id' not in existing_columns:
        op.add_column('gg_approvals', sa.Column('message_id', sa.String(length=36), nullable=True))
        print("Added column: message_id")
    
    if 'channel_id' not in existing_columns:
        op.add_column('gg_approvals', sa.Column('channel_id', sa.String(length=36), nullable=True))
        print("Added column: channel_id")
    
    if 'title' not in existing_columns:
        op.add_column('gg_approvals', sa.Column('title', sa.String(length=255), nullable=True))
        print("Added column: title")
    
    if 'description' not in existing_columns:
        op.add_column('gg_approvals', sa.Column('description', sa.Text(), nullable=True))
        print("Added column: description")
    
    if 'status' not in existing_columns:
        op.add_column('gg_approvals', sa.Column('status', sa.String(length=20), nullable=True, default='pending'))
        print("Added column: status")
    
    if 'is_active' not in existing_columns:
        op.add_column('gg_approvals', sa.Column('is_active', sa.String(length=1), nullable=True, default='Y'))
        print("Added column: is_active")
    
    if 'created_at' not in existing_columns:
        op.add_column('gg_approvals', sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')))
        print("Added column: created_at")
    
    if 'updated_at' not in existing_columns:
        op.add_column('gg_approvals', sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')))
        print("Added column: updated_at")


def downgrade() -> None:
    # Check if table exists
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()
    
    if 'gg_approvals' not in existing_tables:
        return
    
    existing_columns = [col['name'] for col in inspector.get_columns('gg_approvals')]
    
    # Revert column names if they exist
    if 'requested_by_user_id' in existing_columns and 'requested_by' not in existing_columns:
        op.alter_column('gg_approvals', 'requested_by_user_id', new_column_name='requested_by')
    
    if 'approver_user_id' in existing_columns and 'approver' not in existing_columns:
        op.alter_column('gg_approvals', 'approver_user_id', new_column_name='approver')
    
    # Remove added columns
    for col_name in ['thread_id', 'message_id', 'channel_id', 'title', 'description', 'status', 'is_active', 'created_at', 'updated_at']:
        if col_name in existing_columns:
            op.drop_column('gg_approvals', col_name) 