"""add_query_id_column_to_messages

Revision ID: 86c6d78e1615
Revises: 7ed87e41a4d2
Create Date: 2025-08-08 23:00:05.083372

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '86c6d78e1615'
down_revision = '7ed87e41a4d2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add query_id column to gg_messages table if it doesn't exist
    # This migration is designed to work whether the column exists or not
    connection = op.get_bind()
    
    # Check if query_id column already exists in gg_messages
    inspector = sa.inspect(connection)
    messages_columns = [col['name'] for col in inspector.get_columns('gg_messages')]
    
    if 'query_id' not in messages_columns:
        # Add query_id column to gg_messages table
        op.add_column('gg_messages', sa.Column('query_id', postgresql.UUID(as_uuid=True), nullable=True))
        
        # Create index for query_id column
        op.create_index('idx_message_query_id', 'gg_messages', ['query_id'])
    
    # Add app_key column to gg_apps table if it doesn't exist
    apps_columns = [col['name'] for col in inspector.get_columns('gg_apps')]
    
    if 'app_key' not in apps_columns:
        # Add app_key column to gg_apps table
        op.add_column('gg_apps', sa.Column('app_key', sa.String(100), nullable=True))
        
        # Create unique index on app_key
        op.create_index('idx_app_key_unique', 'gg_apps', ['app_key'], unique=True)
        
        # Update existing records to have a default app_key based on app_name
        op.execute("""
            UPDATE gg_apps 
            SET app_key = LOWER(REPLACE(app_name, ' ', '_'))
            WHERE app_key IS NULL
        """)
        
        # Make app_key not nullable after setting default values
        op.alter_column('gg_apps', 'app_key', nullable=False)


def downgrade() -> None:
    # Drop index for query_id column if it exists
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    indexes = [idx['name'] for idx in inspector.get_indexes('gg_messages')]
    
    if 'idx_message_query_id' in indexes:
        op.drop_index('idx_message_query_id', table_name='gg_messages')
    
    # Drop query_id column from gg_messages table if it exists
    columns = [col['name'] for col in inspector.get_columns('gg_messages')]
    if 'query_id' in columns:
        op.drop_column('gg_messages', 'query_id')
    
    # Drop app_key related changes from gg_apps table if they exist
    app_indexes = [idx['name'] for idx in inspector.get_indexes('gg_apps')]
    if 'idx_app_key_unique' in app_indexes:
        op.drop_index('idx_app_key_unique', table_name='gg_apps')
    
    app_columns = [col['name'] for col in inspector.get_columns('gg_apps')]
    if 'app_key' in app_columns:
        op.drop_column('gg_apps', 'app_key') 