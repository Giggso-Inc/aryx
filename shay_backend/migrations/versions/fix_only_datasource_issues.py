"""fix_only_datasource_issues

Revision ID: fix_only_datasource_issues
Revises: fix_is_connected_default_value
Create Date: 2025-01-27 10:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fix_only_datasource_issues'
down_revision = 'fix_is_connected_default_value'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Only fix the datasource table - don't touch other services' tables
    
    # 1. Fix the giggso_vault_id column type (if needed)
    # This is safe as it only affects the datasource table
    try:
        op.alter_column('gg_datasources', 'giggso_vault_id',
                       existing_type=sa.VARCHAR(length=100),
                       type_=sa.UUID(),
                       existing_nullable=True)
    except Exception:
        # Column might already be UUID type, ignore error
        pass
    
    # 2. Fix the index names to match what the model expects
    # Drop old index if it exists
    try:
        op.drop_index('idx_datasource_is_connected', table_name='gg_datasources')
    except Exception:
        # Index might not exist, ignore error
        pass
    
    # Create the correct index name
    try:
        op.create_index('idx_datasource_connected', 'gg_datasources', ['is_connected'])
    except Exception:
        # Index might already exist, ignore error
        pass


def downgrade() -> None:
    # Revert the changes
    try:
        op.drop_index('idx_datasource_connected', table_name='gg_datasources')
    except Exception:
        pass
    
    try:
        op.create_index('idx_datasource_is_connected', 'gg_datasources', ['is_connected'])
    except Exception:
        pass
