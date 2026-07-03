"""fix_datasource_schema_remove_description_add_log_type

Revision ID: 91b4b06b5ac9
Revises: 176748bc1a11
Create Date: 2025-08-29 12:38:22.279020

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '91b4b06b5ac9'
down_revision = '176748bc1a11'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Fix datasource schema by removing description and adding log_type"""
    
    # Get connection and inspector
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    # Get current columns
    columns = [col['name'] for col in inspector.get_columns('gg_datasources')]
    
    # Step 1: Remove description column if it exists
    if 'description' in columns:
        op.drop_column('gg_datasources', 'description')
        print("✅ Successfully removed 'description' column from datasources table")
    else:
        print("ℹ️  'description' column does not exist in datasources table")
    
    # Step 2: Add log_type column if it doesn't exist
    if 'log_type' not in columns:
        op.add_column('gg_datasources', 
                      sa.Column('log_type', sa.String(100), nullable=True))
        print("✅ Successfully added 'log_type' column to datasources table")
    else:
        print("ℹ️  'log_type' column already exists in datasources table")
    
    # Step 3: Create index on log_type column if it doesn't exist
    try:
        op.create_index('idx_datasource_log_type', 'gg_datasources', ['log_type'])
        print("✅ Successfully created index on log_type column")
    except Exception as e:
        # Index might already exist, which is fine
        print(f"ℹ️  Index creation: {e}")


def downgrade() -> None:
    """Revert the changes by adding description back and removing log_type"""
    
    # Get connection and inspector
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    # Get current columns
    columns = [col['name'] for col in inspector.get_columns('gg_datasources')]
    
    # Step 1: Add back description column
    if 'description' not in columns:
        op.add_column('gg_datasources', 
                      sa.Column('description', sa.Text(), nullable=True))
        print("✅ Successfully added back 'description' column to datasources table")
    else:
        print("ℹ️  'description' column already exists in datasources table")
    
    # Step 2: Remove log_type column and its index
    if 'log_type' in columns:
        # Drop index first
        try:
            op.drop_index('idx_datasource_log_type', 'gg_datasources')
            print("✅ Successfully dropped index on log_type column")
        except Exception as e:
            print(f"ℹ️  Index drop: {e}")
        
        # Then drop column
        op.drop_column('gg_datasources', 'log_type')
        print("✅ Successfully removed 'log_type' column from datasources table")
    else:
        print("ℹ️  'log_type' column does not exist in datasources table") 