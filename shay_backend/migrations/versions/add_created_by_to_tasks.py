"""Add created_by column to tasks table

Revision ID: add_created_by_to_tasks
Revises: 
Create Date: 2025-08-18

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_created_by_to_tasks'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Add created_by column to gg_tasks table
    op.add_column('gg_tasks', sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True))
    
    # Create index on created_by column
    op.create_index(op.f('ix_gg_tasks_created_by'), 'gg_tasks', ['created_by'], unique=False)


def downgrade():
    # Drop index first
    op.drop_index(op.f('ix_gg_tasks_created_by'), table_name='gg_tasks')
    
    # Drop created_by column
    op.drop_column('gg_tasks', 'created_by')
