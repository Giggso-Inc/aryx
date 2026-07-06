"""add gg_email_notify_settings and gg_shortened_urls tables

Revision ID: d3f8a12b9c4e
Revises: create_support_requests, add_embedding_columns, eff5d16184fb, c4bb1f99bbd3, create_gg_app_connections_table
Create Date: 2026-07-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'd3f8a12b9c4e'
down_revision = (
    'create_support_requests',
    'add_embedding_columns',
    'eff5d16184fb',
    'c4bb1f99bbd3',
    'create_gg_app_connections_table',
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'gg_email_notify_settings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('routine', sa.BigInteger(), nullable=True),
        sa.Column('resource_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('is_notification_enabled', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('post_enabled', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('app_enabled', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('blocker_enabled', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('approval_pending_enabled', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('meeting_enabled', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('task_enabled', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('mention_enabled', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('reply_enabled', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('chat_enabled', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('friend_enabled', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_time', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_time', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('last_email_notify_time', sa.DateTime(), nullable=True),
    )
    op.create_index('idx_email_notify_resource', 'gg_email_notify_settings', ['resource_id'])
    op.create_index('idx_email_notify_routine', 'gg_email_notify_settings', ['routine'])
    op.create_index('idx_email_notify_resource_routine', 'gg_email_notify_settings',
                    ['resource_id', 'routine'])

    op.create_table(
        'gg_shortened_urls',
        sa.Column('short_link', sa.String(7), primary_key=True),
        sa.Column('original_url', sa.String(2048), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('thread_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('channel_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('entity_type', sa.String(50), nullable=True),
        sa.Column('last_updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('idx_shortened_url_used_at', 'gg_shortened_urls', ['used_at'])
    op.create_index('idx_shortened_url_thread', 'gg_shortened_urls', ['thread_id'])
    op.create_index('idx_shortened_url_channel', 'gg_shortened_urls', ['channel_id'])


def downgrade() -> None:
    op.drop_index('idx_shortened_url_channel', table_name='gg_shortened_urls')
    op.drop_index('idx_shortened_url_thread', table_name='gg_shortened_urls')
    op.drop_index('idx_shortened_url_used_at', table_name='gg_shortened_urls')
    op.drop_table('gg_shortened_urls')

    op.drop_index('idx_email_notify_resource_routine', table_name='gg_email_notify_settings')
    op.drop_index('idx_email_notify_routine', table_name='gg_email_notify_settings')
    op.drop_index('idx_email_notify_resource', table_name='gg_email_notify_settings')
    op.drop_table('gg_email_notify_settings')
