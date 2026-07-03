"""add_app_key_to_apps_table

Revision ID: e31613234d66
Revises: ecbda37a5c80
Create Date: 2025-08-07 21:36:29.200478

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e31613234d66'
down_revision = 'ecbda37a5c80'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add app_key column to gg_apps table
    op.add_column('gg_apps', sa.Column('app_key', sa.String(100), nullable=True))
    
    # Create unique index on app_key
    op.create_index('idx_app_key_unique', 'gg_apps', ['app_key'], unique=True)
    
    # Update existing records to have a default app_key based on app_name
    # This is a temporary measure - in production, you'd want to set proper app_keys
    op.execute("""
        UPDATE gg_apps 
        SET app_key = LOWER(REPLACE(app_name, ' ', '_'))
        WHERE app_key IS NULL
    """)
    
    # Make app_key not nullable after setting default values
    op.alter_column('gg_apps', 'app_key', nullable=False)


def downgrade() -> None:
    # Remove unique index
    op.drop_index('idx_app_key_unique', table_name='gg_apps')
    
    # Remove app_key column
    op.drop_column('gg_apps', 'app_key') 