"""Create only essential project tables

Revision ID: create_only_project_tables
Revises: fix_only_datasource_issues
Create Date: 2025-08-13 11:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'create_only_project_tables'
down_revision = 'fix_only_datasource_issues'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Only create tables that don't exist and are needed for this project
    
    # Create gg_users table if it doesn't exist
    op.execute("""
        CREATE TABLE IF NOT EXISTS gg_users (
            id UUID PRIMARY KEY,
            name VARCHAR(255),
            email_id VARCHAR(255) UNIQUE NOT NULL,
            avatar_url TEXT,
            company_id UUID,
            role VARCHAR(50) DEFAULT 'member',
            is_active BOOLEAN DEFAULT true,
            is_verified BOOLEAN DEFAULT false,
            google_id VARCHAR(255),
            oauth_provider VARCHAR(50),
            preferences JSONB,
            last_login TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_datetime TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_datetime TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            password_hash VARCHAR(255)
        )
    """)
    
    # Create gg_company table if it doesn't exist
    op.execute("""
        CREATE TABLE IF NOT EXISTS gg_company (
            id UUID PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            domain VARCHAR(255) UNIQUE,
            industry VARCHAR(100),
            status VARCHAR(50) DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create gg_workspace table if it doesn't exist
    op.execute("""
        CREATE TABLE IF NOT EXISTS gg_workspace (
            id UUID PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            company_id UUID REFERENCES gg_company(id),
            is_active BOOLEAN DEFAULT true,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create gg_channels table if it doesn't exist
    op.execute("""
        CREATE TABLE IF NOT EXISTS gg_channels (
            id UUID PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            workspace_id UUID REFERENCES gg_workspace(id),
            company_id UUID REFERENCES gg_company(id),
            channel_type VARCHAR(50) DEFAULT 'general',
            is_active BOOLEAN DEFAULT true,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create gg_channel_members table if it doesn't exist
    op.execute("""
        CREATE TABLE IF NOT EXISTS gg_channel_members (
            id UUID PRIMARY KEY,
            channel_id UUID REFERENCES gg_channels(id),
            user_id UUID REFERENCES gg_users(id),
            role VARCHAR(50) DEFAULT 'member',
            is_active BOOLEAN DEFAULT true,
            permissions JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(channel_id, user_id)
        )
    """)
    
    # Create gg_messages table if it doesn't exist
    op.execute("""
        CREATE TABLE IF NOT EXISTS gg_messages (
            id UUID PRIMARY KEY,
            content TEXT NOT NULL,
            user_id UUID REFERENCES gg_users(id),
            channel_id UUID REFERENCES gg_channels(id),
            thread_id UUID,
            message_type VARCHAR(50) DEFAULT 'text',
            is_ai_processed BOOLEAN DEFAULT false,
            query_id VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create gg_threads table if it doesn't exist
    op.execute("""
        CREATE TABLE IF NOT EXISTS gg_threads (
            id UUID PRIMARY KEY,
            title VARCHAR(255),
            channel_id UUID REFERENCES gg_channels(id),
            created_by UUID REFERENCES gg_users(id),
            is_active BOOLEAN DEFAULT true,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create indexes for performance
    op.execute("CREATE INDEX IF NOT EXISTS idx_channel_members_channel_user ON gg_channel_members(channel_id, user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_channel_members_user ON gg_channel_members(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_messages_channel ON gg_messages(channel_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_messages_user ON gg_messages(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_channels_workspace ON gg_channels(workspace_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_users_company ON gg_users(company_id)")


def downgrade() -> None:
    # Drop only the tables we created, not other project tables
    op.execute("DROP TABLE IF EXISTS gg_channel_members CASCADE")
    op.execute("DROP TABLE IF EXISTS gg_messages CASCADE")
    op.execute("DROP TABLE IF EXISTS gg_threads CASCADE")
    op.execute("DROP TABLE IF EXISTS gg_channels CASCADE")
    op.execute("DROP TABLE IF EXISTS gg_workspace CASCADE")
    op.execute("DROP TABLE IF EXISTS gg_users CASCADE")
    op.execute("DROP TABLE IF EXISTS gg_company CASCADE")
