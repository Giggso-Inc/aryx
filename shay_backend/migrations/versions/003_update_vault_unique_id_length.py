"""Update vault_unique_id column length

Revision ID: 003
Revises: 002
Create Date: 2025-08-06 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    """Update vault_unique_id column length"""
    # Update the vault_unique_id column to VARCHAR(255)
    op.alter_column('gg_vault', 'vault_unique_id',
                    existing_type=sa.String(length=50),
                    type_=sa.String(length=255),
                    existing_nullable=True)


def downgrade():
    """Revert vault_unique_id column length"""
    # Revert the vault_unique_id column back to VARCHAR(50)
    op.alter_column('gg_vault', 'vault_unique_id',
                    existing_type=sa.String(length=255),
                    type_=sa.String(length=50),
                    existing_nullable=True)
