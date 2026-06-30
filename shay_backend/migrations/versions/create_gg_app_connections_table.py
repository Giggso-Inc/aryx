"""Create gg_app_connections table

New unified app-connection table supporting workspace / channel / thread scopes.
This is a separate table from the existing gg_app_accounts — no alteration to
the existing table is performed.

Revision ID: create_gg_app_connections_table
Revises:
Create Date: 2026-03-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'create_gg_app_connections_table'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # -----------------------------------------------------------------------
    # Create gg_app_connections table
    # -----------------------------------------------------------------------
    op.create_table(
        'gg_app_connections',
        # Primary key
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),

        # Which app (nullable to handle app deletions via SET NULL)
        sa.Column('app_id', postgresql.UUID(as_uuid=True), nullable=True),

        # Exclusive arc — exactly one scope FK is set per row
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('channel_id',   postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('thread_id',    postgresql.UUID(as_uuid=True), nullable=True),

        # Scope label mirrors the FK that is set
        sa.Column('level', sa.String(length=20), nullable=False),

        # Who connected the app
        sa.Column('connected_by', postgresql.UUID(as_uuid=True), nullable=False),

        # Connection metadata
        sa.Column('connection_name',     sa.String(length=255),                           nullable=True),
        sa.Column('connection_status',   sa.String(length=50),                            nullable=False, server_default='active'),
        sa.Column('connection_settings', postgresql.JSONB(astext_type=sa.Text()),         nullable=True),
        sa.Column('api_key',             sa.String(length=500),                           nullable=True),
        sa.Column('webhook_url',         sa.String(length=500),                           nullable=True),
        sa.Column('callback_url',        sa.String(length=500),                           nullable=True),
        sa.Column('last_sync_at',        sa.DateTime(),                                   nullable=True),
        sa.Column('sync_status',         sa.String(length=50),                            nullable=True),
        sa.Column('error_message',       sa.Text(),                                       nullable=True),
        sa.Column('is_active',           sa.Boolean(),                                    nullable=False, server_default=sa.text('true')),
        sa.Column('auto_sync',           sa.Boolean(),                                    nullable=False, server_default=sa.text('false')),
        sa.Column('sync_interval',       sa.Integer(),                                    nullable=False, server_default='3600'),

        # Provider / OAuth fields
        sa.Column('provider',            sa.String(length=50),                            nullable=True),
        sa.Column('provider_account_id', sa.String(length=255),                          nullable=True),
        sa.Column('auth_type',           sa.String(length=50),                            nullable=True, server_default='oauth2'),
        sa.Column('provider_metadata',   postgresql.JSONB(astext_type=sa.Text()),         nullable=True),
        sa.Column('last_token_refresh',  sa.DateTime(),                                   nullable=True),
        sa.Column('token_expires_at',    sa.DateTime(),                                   nullable=True),

        # Timestamps
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),

        # Foreign key constraints
        sa.ForeignKeyConstraint(['app_id'],       ['gg_apps.id'],      ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['workspace_id'], ['gg_workspace.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['channel_id'],   ['gg_channels.id'],  ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['thread_id'],    ['gg_threads.id'],   ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['connected_by'], ['gg_users.id'],     ondelete='CASCADE'),

        # Primary key constraint
        sa.PrimaryKeyConstraint('id'),

        # Exclusive arc CHECK constraint — exactly one scope FK must be set
        sa.CheckConstraint(
            "(level = 'workspace' AND workspace_id IS NOT NULL AND channel_id IS NULL   AND thread_id IS NULL) OR "
            "(level = 'channel'   AND channel_id   IS NOT NULL AND workspace_id IS NULL AND thread_id IS NULL) OR "
            "(level = 'thread'    AND thread_id    IS NOT NULL AND workspace_id IS NULL AND channel_id IS NULL)",
            name='chk_gg_app_connections_exclusive_arc',
        ),
    )

    # -----------------------------------------------------------------------
    # Basic column indexes
    # -----------------------------------------------------------------------
    op.create_index('idx_gg_app_connections_id',           'gg_app_connections', ['id'])
    op.create_index('idx_gg_app_connections_app_id',       'gg_app_connections', ['app_id'])
    op.create_index('idx_gg_app_connections_workspace_id', 'gg_app_connections', ['workspace_id'])
    op.create_index('idx_gg_app_connections_channel_id',   'gg_app_connections', ['channel_id'])
    op.create_index('idx_gg_app_connections_thread_id',    'gg_app_connections', ['thread_id'])
    op.create_index('idx_gg_app_connections_connected_by_created_at', 'gg_app_connections', ['connected_by', 'created_at'])
    op.create_index('idx_gg_app_connections_status_time',  'gg_app_connections', ['connection_status', 'created_at'])
    op.create_index('idx_gg_app_connections_sync_status',  'gg_app_connections', ['sync_status', 'last_sync_at'])
    op.create_index('idx_gg_app_connections_active_sync',  'gg_app_connections', ['is_active', 'auto_sync'])
    op.create_index('idx_gg_app_connections_level',        'gg_app_connections', ['level'])

    # -----------------------------------------------------------------------
    # Partial unique indexes — one app connection per (scope FK, app_id) per level
    # -----------------------------------------------------------------------
    op.create_index(
        'uk_gg_app_connections_workspace',
        'gg_app_connections',
        ['workspace_id', 'app_id'],
        unique=True,
        postgresql_where=sa.text("level = 'workspace'"),
    )
    op.create_index(
        'uk_gg_app_connections_channel',
        'gg_app_connections',
        ['channel_id', 'app_id'],
        unique=True,
        postgresql_where=sa.text("level = 'channel'"),
    )
    op.create_index(
        'uk_gg_app_connections_thread',
        'gg_app_connections',
        ['thread_id', 'app_id'],
        unique=True,
        postgresql_where=sa.text("level = 'thread'"),
    )

    # -----------------------------------------------------------------------
    # updated_at auto-update trigger
    # -----------------------------------------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION update_gg_app_connections_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_gg_app_connections_updated_at
        BEFORE UPDATE ON gg_app_connections
        FOR EACH ROW
        EXECUTE FUNCTION update_gg_app_connections_updated_at();
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_gg_app_connections_updated_at ON gg_app_connections;")
    op.execute("DROP FUNCTION IF EXISTS update_gg_app_connections_updated_at();")
    op.drop_table('gg_app_connections')
