"""Create Approval Table Fix

This migration ensures the approval table and all required columns exist.
It handles both table creation and column addition scenarios with proper
precondition checks to avoid conflicts.

Revision ID: 2d80b4405b2a
Revises: 6b3d995167ea
Create Date: 2025-08-19 16:10:50.973634

Author: Karthick Chandrasekar
Date: 19-08-2025
Version: 1.0.0

Purpose: Fix approval table structure and ensure all required columns exist
"""
# Alembic migration operations
from alembic import op
# SQLAlchemy for database schema operations
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2d80b4405b2a'
down_revision = '6b3d995167ea'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if table already exists
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()
    
    if 'gg_approvals' not in existing_tables:
        # Create approval table from scratch
        op.create_table('gg_approvals',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('thread_id', sa.String(length=36), nullable=False),
            sa.Column('message_id', sa.String(length=36), nullable=False),
            sa.Column('channel_id', sa.String(length=36), nullable=False),
            sa.Column('requested_by_user_id', sa.String(length=36), nullable=False),
            sa.Column('approver_user_id', sa.String(length=36), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False, default='pending'),
            sa.Column('title', sa.String(length=255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('approval_notes', sa.Text(), nullable=True),
            sa.Column('rejection_reason', sa.Text(), nullable=True),
            sa.Column('comment', sa.Text(), nullable=True),
            sa.Column('is_active', sa.String(length=1), nullable=False, default='Y'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('approved_at', sa.DateTime(), nullable=True),
            sa.Column('rejected_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        print("Table 'gg_approvals' created successfully")
    else:
        # Table exists, check and add missing columns
        print("Table 'gg_approvals' exists, checking columns...")
        existing_columns = [col['name'] for col in inspector.get_columns('gg_approvals')]
        
        # Add missing columns
        if 'approved_at' not in existing_columns:
            op.add_column('gg_approvals', sa.Column('approved_at', sa.DateTime(), nullable=True))
            print("Added column: approved_at")
        
        if 'rejected_at' not in existing_columns:
            op.add_column('gg_approvals', sa.Column('rejected_at', sa.DateTime(), nullable=True))
            print("Added column: rejected_at")
        
        if 'comment' not in existing_columns:
            op.add_column('gg_approvals', sa.Column('comment', sa.Text(), nullable=True))
            print("Added column: comment")
    
    # Create indexes
    existing_indexes = [idx['name'] for idx in inspector.get_indexes('gg_approvals')] if 'gg_approvals' in existing_tables else []
    
    if 'idx_approval_thread_id' not in existing_indexes:
        op.create_index('idx_approval_thread_id', 'gg_approvals', ['thread_id'])
    if 'idx_approval_status' not in existing_indexes:
        op.create_index('idx_approval_status', 'gg_approvals', ['status'])


def downgrade() -> None:
    # Drop indexes
    inspector = sa.inspect(op.get_bind())
    existing_indexes = [idx['name'] for idx in inspector.get_indexes('gg_approvals')] if 'gg_approvals' in inspector.get_table_names() else []
    
    if 'idx_approval_status' in existing_indexes:
        op.drop_index('idx_approval_status', table_name='gg_approvals')
    if 'idx_approval_thread_id' in existing_indexes:
        op.drop_index('idx_approval_thread_id', table_name='gg_approvals')
    
    # Drop table if it exists
    if 'gg_approvals' in inspector.get_table_names():
        op.drop_table('gg_approvals') 