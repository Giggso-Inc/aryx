"""Create checklist table

Revision ID: create_checklist_table
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'create_checklist_table'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create checklist table
    op.create_table('gg_checklists',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('text', sa.String(length=500), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('is_completed', sa.Boolean(), nullable=False, default=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('completed_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('checklist_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['task_id'], ['gg_tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes
    op.create_index('idx_checklist_task_order', 'gg_checklists', ['task_id', 'order_index'])
    op.create_index('idx_checklist_task_status', 'gg_checklists', ['task_id', 'is_completed'])
    op.create_index('idx_checklist_completed_by', 'gg_checklists', ['completed_by'])
    op.create_index('idx_checklist_created_at', 'gg_checklists', ['created_at'])


def downgrade():
    # Drop checklist table
    op.drop_table('gg_checklists')
