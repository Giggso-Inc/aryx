"""fix_user_table_structure

Revision ID: ecbda37a5c80
Revises: 4816283117c2
Create Date: 2025-08-07 17:28:23.701853

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ecbda37a5c80'
down_revision = '4816283117c2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename email column to email_id to match the model
    op.alter_column('gg_users', 'email', new_column_name='email_id')
    
    # Add password_hash column
    op.add_column('gg_users', sa.Column('password_hash', sa.Text(), nullable=True))
    
    # Add created_datetime and updated_datetime columns
    op.add_column('gg_users', sa.Column('created_datetime', sa.DateTime(), nullable=True))
    op.add_column('gg_users', sa.Column('updated_datetime', sa.DateTime(), nullable=True))
    
    # Set default values for existing rows
    op.execute("UPDATE gg_users SET created_datetime = created_at, updated_datetime = updated_at")
    
    # Make the new columns NOT NULL after setting defaults
    op.alter_column('gg_users', 'created_datetime', nullable=False)
    op.alter_column('gg_users', 'updated_datetime', nullable=False)


def downgrade() -> None:
    # Remove the new columns
    op.drop_column('gg_users', 'updated_datetime')
    op.drop_column('gg_users', 'password_hash')
    op.drop_column('gg_users', 'created_datetime')
    
    # Rename email_id back to email
    op.alter_column('gg_users', 'email_id', new_column_name='email') 