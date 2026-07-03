"""Create approval table

Revision ID: create_approval_table
Revises: remove_duplicate_user_columns
Create Date: 2025-01-20 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'create_approval_table'
down_revision = 'remove_duplicate_user_columns'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if table already exists
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()
    
    if 'gg_approvals' not in existing_tables:
        # Create approval table from scratch
        op.create_table('gg_approvals',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('thread_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('message_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('channel_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('requested_by_user_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('approver_user_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False, default='pending'),
            sa.Column('title', sa.String(length=255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('approval_notes', sa.Text(), nullable=True),
            sa.Column('rejection_reason', sa.Text(), nullable=True),
            sa.Column('comment', sa.Text(), nullable=True),  # New field for approve/reject comments
            sa.Column('is_active', sa.String(length=1), nullable=False, default='Y'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('approved_at', sa.DateTime(), nullable=True),
            sa.Column('rejected_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        print("Table 'gg_approvals' created successfully")
    else:
        # Table exists, check and modify columns as needed
        print("Table 'gg_approvals' exists, checking columns...")
        existing_columns = [col['name'] for col in inspector.get_columns('gg_approvals')]
        
        # Add missing columns
        if 'thread_id' not in existing_columns:
            op.add_column('gg_approvals', sa.Column('thread_id', postgresql.UUID(as_uuid=True), nullable=True))
            print("Added column: thread_id")
        
        if 'message_id' not in existing_columns:
            op.add_column('gg_approvals', sa.Column('message_id', postgresql.UUID(as_uuid=True), nullable=True))
            print("Added column: message_id")
        
        if 'channel_id' not in existing_columns:
            op.add_column('gg_approvals', sa.Column('channel_id', postgresql.UUID(as_uuid=True), nullable=True))
            print("Added column: channel_id")
        
        if 'title' not in existing_columns:
            op.add_column('gg_approvals', sa.Column('title', sa.String(length=255), nullable=True))
            print("Added column: title")
        
        if 'description' not in existing_columns:
            op.add_column('gg_approvals', sa.Column('description', sa.Text(), nullable=True))
            print("Added column: description")
        
        if 'approval_notes' not in existing_columns:
            op.add_column('gg_approvals', sa.Column('approval_notes', sa.Text(), nullable=True))
            print("Added column: approval_notes")
        
        if 'rejection_reason' not in existing_columns:
            op.add_column('gg_approvals', sa.Column('rejection_reason', sa.Text(), nullable=True))
            print("Added column: rejection_reason")
        
        if 'comment' not in existing_columns:
            op.add_column('gg_approvals', sa.Column('comment', sa.Text(), nullable=True))
            print("Added column: comment")
        
        if 'is_active' not in existing_columns:
            op.add_column('gg_approvals', sa.Column('is_active', sa.String(length=1), nullable=True, default='Y'))
            print("Added column: is_active")
        
        # Add missing user ID columns if they don't exist
        if 'requested_by_user_id' not in existing_columns:
            op.add_column('gg_approvals', sa.Column('requested_by_user_id', postgresql.UUID(as_uuid=True), nullable=True))
            print("Added column: requested_by_user_id")
        
        if 'approver_user_id' not in existing_columns:
            op.add_column('gg_approvals', sa.Column('approver_user_id', postgresql.UUID(as_uuid=True), nullable=True))
            print("Added column: approver_user_id")
        
        # Add missing timestamp columns if they don't exist
        if 'approved_at' not in existing_columns:
            op.add_column('gg_approvals', sa.Column('approved_at', sa.DateTime(), nullable=True))
            print("Added column: approved_at")
        
        if 'rejected_at' not in existing_columns:
            op.add_column('gg_approvals', sa.Column('rejected_at', sa.DateTime(), nullable=True))
            print("Added column: rejected_at")
        
        # Modify existing columns if needed
        if 'status' in existing_columns:
            # Check if status column needs modification
            status_col = next(col for col in inspector.get_columns('gg_approvals') if col['name'] == 'status')
            if status_col['type'].length != 20:
                op.alter_column('gg_approvals', 'status', type_=sa.String(length=20))
                print("Modified column: status")
        
        # Remove old columns if they exist (like task_id)
        if 'task_id' in existing_columns:
            op.drop_column('gg_approvals', 'task_id')
            print("Removed column: task_id")
        
        if 'approval_type' in existing_columns:
            op.drop_column('gg_approvals', 'approval_type')
            print("Removed column: approval_type")
        
        if 'priority' in existing_columns:
            op.drop_column('gg_approvals', 'priority')
            print("Removed column: priority")
        
        if 'approval_metadata' in existing_columns:
            op.drop_column('gg_approvals', 'approval_metadata')
            print("Removed column: approval_metadata")
    
    # Create indexes with precondition checks
    existing_indexes = [idx['name'] for idx in inspector.get_indexes('gg_approvals')] if 'gg_approvals' in existing_tables else []
    
    if 'idx_approval_id' not in existing_indexes:
        op.create_index('idx_approval_id', 'gg_approvals', ['id'])
    if 'idx_approval_thread_id' not in existing_indexes:
        op.create_index('idx_approval_thread_id', 'gg_approvals', ['thread_id'])
    if 'idx_approval_message_id' not in existing_indexes:
        op.create_index('idx_approval_message_id', 'gg_approvals', ['message_id'])
    if 'idx_approval_channel_id' not in existing_indexes:
        op.create_index('idx_approval_channel_id', 'gg_approvals', ['channel_id'])
    if 'idx_approval_requested_by_user_id' not in existing_indexes:
        op.create_index('idx_approval_requested_by_user_id', 'gg_approvals', ['requested_by_user_id'])
    if 'idx_approval_approver_user_id' not in existing_indexes:
        op.create_index('idx_approval_approver_user_id', 'gg_approvals', ['approver_user_id'])
    if 'idx_approval_status' not in existing_indexes:
        op.create_index('idx_approval_status', 'gg_approvals', ['status'])
    if 'idx_thread_active_approval' not in existing_indexes:
        op.create_index('idx_thread_active_approval', 'gg_approvals', ['thread_id', 'is_active'])
    if 'idx_channel_status' not in existing_indexes:
        op.create_index('idx_channel_status', 'gg_approvals', ['channel_id', 'status'])
    if 'idx_approver_status' not in existing_indexes:
        op.create_index('idx_approver_status', 'gg_approvals', ['approver_user_id', 'status'])
    if 'idx_requested_by_status' not in existing_indexes:
        op.create_index('idx_requested_by_status', 'gg_approvals', ['requested_by_user_id', 'status'])
    
    # Create foreign key constraints with precondition checks
    existing_fks = [fk['name'] for fk in inspector.get_foreign_keys('gg_approvals')] if 'gg_approvals' in existing_tables else []
    
    if 'fk_approval_thread_id' not in existing_fks:
        op.create_foreign_key('fk_approval_thread_id', 'gg_approvals', 'gg_threads', ['thread_id'], ['id'], ondelete='CASCADE')
    if 'fk_approval_message_id' not in existing_fks:
        op.create_foreign_key('fk_approval_message_id', 'gg_approvals', 'gg_messages', ['message_id'], ['id'], ondelete='CASCADE')
    if 'fk_approval_channel_id' not in existing_fks:
        op.create_foreign_key('fk_approval_channel_id', 'gg_approvals', 'gg_channels', ['channel_id'], ['id'], ondelete='CASCADE')
    if 'fk_approval_requested_by_user_id' not in existing_fks:
        op.create_foreign_key('fk_approval_requested_by_user_id', 'gg_approvals', 'gg_users', ['requested_by_user_id'], ['id'], ondelete='CASCADE')
    if 'fk_approval_approver_user_id' not in existing_fks:
        op.create_foreign_key('fk_approval_approver_user_id', 'gg_approvals', 'gg_users', ['approver_user_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    # Check if table exists before trying to drop
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()
    
    if 'gg_approvals' not in existing_tables:
        print("Table 'gg_approvals' does not exist, skipping downgrade")
        return
    
    # Drop foreign key constraints with precondition checks
    existing_fks = [fk['name'] for fk in inspector.get_foreign_keys('gg_approvals')]
    
    if 'fk_approval_approver_user_id' in existing_fks:
        op.drop_constraint('fk_approval_approver_user_id', 'gg_approvals', type_='foreignkey')
    if 'fk_approval_requested_by_user_id' in existing_fks:
        op.drop_constraint('fk_approval_requested_by_user_id', 'gg_approvals', type_='foreignkey')
    if 'fk_approval_channel_id' in existing_fks:
        op.drop_constraint('fk_approval_channel_id', 'gg_approvals', type_='foreignkey')
    if 'fk_approval_message_id' in existing_fks:
        op.drop_constraint('fk_approval_message_id', 'gg_approvals', type_='foreignkey')
    if 'fk_approval_thread_id' in existing_fks:
        op.drop_constraint('fk_approval_thread_id', 'gg_approvals', type_='foreignkey')
    
    # Drop indexes with precondition checks
    existing_indexes = [idx['name'] for idx in inspector.get_indexes('gg_approvals')]
    
    if 'idx_requested_by_status' in existing_indexes:
        op.drop_index('idx_requested_by_status', table_name='gg_approvals')
    if 'idx_approver_status' in existing_indexes:
        op.drop_index('idx_approver_status', table_name='gg_approvals')
    if 'idx_channel_status' in existing_indexes:
        op.drop_index('idx_channel_status', table_name='gg_approvals')
    if 'idx_thread_active_approval' in existing_indexes:
        op.drop_index('idx_thread_active_approval', table_name='gg_approvals')
    if 'idx_approval_status' in existing_indexes:
        op.drop_index('idx_approval_status', table_name='gg_approvals')
    if 'idx_approval_approver_user_id' in existing_indexes:
        op.drop_index('idx_approval_approver_user_id', table_name='gg_approvals')
    if 'idx_approval_requested_by_user_id' in existing_indexes:
        op.drop_index('idx_approval_requested_by_user_id', table_name='gg_approvals')
    if 'idx_approval_channel_id' in existing_indexes:
        op.drop_index('idx_approval_channel_id', table_name='gg_approvals')
    if 'idx_approval_message_id' in existing_indexes:
        op.drop_index('idx_approval_message_id', table_name='gg_approvals')
    if 'idx_approval_thread_id' in existing_indexes:
        op.drop_index('idx_approval_thread_id', table_name='gg_approvals')
    if 'idx_approval_id' in existing_indexes:
        op.drop_index('idx_approval_id', table_name='gg_approvals')
    
    # Drop table
    op.drop_table('gg_approvals')
