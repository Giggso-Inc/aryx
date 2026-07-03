"""Rename resource_id to user_id in gg_vault table

Revision ID: 002
Revises: 001
Create Date: 2025-08-06 16:15:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands for column rename only ###
    
    # Drop old index
    op.drop_index('idx_vault_resource_id', table_name='gg_vault')
    op.drop_index('ix_gg_vault_resource_id', table_name='gg_vault')
    
    # Rename column
    op.alter_column('gg_vault', 'resource_id', new_column_name='user_id')
    
    # Create new index
    op.create_index('idx_vault_user_id', 'gg_vault', ['user_id'], unique=False)
    op.create_index('ix_gg_vault_user_id', 'gg_vault', ['user_id'], unique=False)
    
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands for rollback ###
    
    # Drop new index
    op.drop_index('ix_gg_vault_user_id', table_name='gg_vault')
    op.drop_index('idx_vault_user_id', table_name='gg_vault')
    
    # Rename column back
    op.alter_column('gg_vault', 'user_id', new_column_name='resource_id')
    
    # Create old index
    op.create_index('idx_vault_resource_id', 'gg_vault', ['resource_id'], unique=False)
    op.create_index('ix_gg_vault_resource_id', 'gg_vault', ['resource_id'], unique=False)
    
    # ### end Alembic commands ###


