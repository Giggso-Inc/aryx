"""Update task due_date from Date to DateTime

Revision ID: update_task_due_date_datetime
Revises: 
Create Date: 2025-01-15

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'update_task_due_date_datetime'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Upgrade: Change due_date column from Date to DateTime"""
    
    # For PostgreSQL, we can use ALTER COLUMN TYPE
    # This will preserve existing data and convert dates to timestamps
    op.execute("""
        ALTER TABLE gg_tasks 
        ALTER COLUMN due_date TYPE TIMESTAMP WITHOUT TIME ZONE 
        USING due_date::timestamp without time zone
    """)
    
    # Update the comment to reflect the change
    op.execute("""
        COMMENT ON COLUMN gg_tasks.due_date IS 'Task due date and time (DateTime instead of Date)'
    """)


def downgrade():
    """Downgrade: Change due_date column back to Date"""
    
    # Convert DateTime back to Date (this will truncate time information)
    op.execute("""
        ALTER TABLE gg_tasks 
        ALTER COLUMN due_date TYPE DATE 
        USING due_date::date
    """)
    
    # Update the comment back
    op.execute("""
        COMMENT ON COLUMN gg_tasks.due_date IS 'Task due date'
    """)


