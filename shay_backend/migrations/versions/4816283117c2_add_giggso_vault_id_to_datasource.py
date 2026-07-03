"""add_giggso_vault_id_to_datasource

Revision ID: 4816283117c2
Revises: 003
Create Date: 2025-08-07 14:16:32.251566

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4816283117c2'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add giggso_vault_id column to gg_datasources table
    op.add_column('gg_datasources', sa.Column('giggso_vault_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
    
    # Create index for the new column
    op.create_index('idx_datasource_giggso_vault_id', 'gg_datasources', ['giggso_vault_id'])


def downgrade() -> None:
    # Drop the index first
    op.drop_index('idx_datasource_giggso_vault_id', table_name='gg_datasources')
    
    # Drop the column
    op.drop_column('gg_datasources', 'giggso_vault_id') 