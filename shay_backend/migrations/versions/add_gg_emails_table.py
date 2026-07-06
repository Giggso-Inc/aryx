"""Add gg_emails table

Adds the gg_emails table used by the email ingestion pipeline and the
email→thread link management flow in messages.py. This table was always
referenced by gg_email_attachments.email_id (FK) and by raw SQL in the
messages router, but was never created by a migration.

Also serves as a merge point for the 5 open migration heads:
  eff5d16184fb, create_support_requests, create_gg_app_connections_table,
  c4bb1f99bbd3, add_embedding_columns

Revision ID: add_gg_emails_table
Revises: eff5d16184fb, create_support_requests, create_gg_app_connections_table, c4bb1f99bbd3, add_embedding_columns
Create Date: 2026-07-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_gg_emails_table'
down_revision = (
    'eff5d16184fb',
    'create_support_requests',
    'create_gg_app_connections_table',
    'c4bb1f99bbd3',
    'add_embedding_columns',
)
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'gg_emails',

        # Primary key
        sa.Column('email_id', postgresql.UUID(as_uuid=True), nullable=False),

        # Thread linkage — managed by messages.py cleanup SQL
        sa.Column('thread_id', postgresql.UUID(as_uuid=True), nullable=True),

        # External email identity
        sa.Column('message_id', sa.String(length=500), nullable=True),
        sa.Column('sender',     sa.String(length=500), nullable=True),
        sa.Column('recipient',  sa.Text(),             nullable=True),
        sa.Column('subject',    sa.Text(),             nullable=True),
        sa.Column('body',       sa.Text(),             nullable=True),
        sa.Column('provider',   sa.String(length=50),  nullable=True),

        # ML pipeline state
        sa.Column('thread_created',   sa.Boolean(), nullable=True, server_default=sa.text('false')),
        sa.Column('ml_processed_at',  sa.DateTime(), nullable=True),

        # Timestamps
        sa.Column('received_at', sa.DateTime(), nullable=True),
        sa.Column('created_at',  sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at',  sa.DateTime(), nullable=False, server_default=sa.text('now()')),

        # Tenant associations
        sa.Column('company_id',   postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('user_id',      postgresql.UUID(as_uuid=True), nullable=True),

        # Constraints
        sa.PrimaryKeyConstraint('email_id'),
        sa.ForeignKeyConstraint(['thread_id'],    ['gg_threads.id'],   ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['company_id'],   ['gg_company.id'],   ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['workspace_id'], ['gg_workspace.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'],      ['gg_users.id'],     ondelete='SET NULL'),
    )

    op.create_index('idx_gg_emails_thread',     'gg_emails', ['thread_id'])
    op.create_index('idx_gg_emails_company',    'gg_emails', ['company_id'])
    op.create_index('idx_gg_emails_message_id', 'gg_emails', ['message_id'])
    op.create_index('idx_gg_emails_user',       'gg_emails', ['user_id'])


def downgrade():
    op.drop_index('idx_gg_emails_user',       table_name='gg_emails')
    op.drop_index('idx_gg_emails_message_id', table_name='gg_emails')
    op.drop_index('idx_gg_emails_company',    table_name='gg_emails')
    op.drop_index('idx_gg_emails_thread',     table_name='gg_emails')
    op.drop_table('gg_emails')
