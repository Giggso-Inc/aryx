"""add_query_id_to_messages_table

Revision ID: 7ed87e41a4d2
Revises: e31613234d66
Create Date: 2025-08-08 20:20:31.742808

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '7ed87e41a4d2'
down_revision = 'e31613234d66'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add query_id column to gg_messages table
    op.add_column('gg_messages', sa.Column('query_id', postgresql.UUID(as_uuid=True), nullable=True))
    
    # Create index for query_id column
    op.create_index('idx_message_query_id', 'gg_messages', ['query_id'])


def downgrade() -> None:
    # Drop index for query_id column
    op.drop_index('idx_message_query_id', table_name='gg_messages')
    
    # Drop query_id column from gg_messages table
    op.drop_column('gg_messages', 'query_id') 