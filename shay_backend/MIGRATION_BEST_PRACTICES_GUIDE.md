# Alembic Migration Best Practices Guide

This guide covers how to properly manage database migrations using Alembic to ensure your database schema changes are automatically reflected across all deployments.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Migration Scenarios](#migration-scenarios)
3. [Automated Deployment Process](#automated-deployment-process)
4. [Best Practices](#best-practices)
5. [Troubleshooting](#troubleshooting)

## Prerequisites

Before starting, ensure you have:
- Alembic properly configured in your project
- Database connection configured
- Models defined using SQLAlchemy ORM

## Migration Scenarios

### 1. Creating a New Table

#### Step 1: Define the Model
```python
# app/models/new_table.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class NewTable(Base):
    __tablename__ = "gg_new_table"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(1000), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Foreign key relationship
    user_id = Column(Integer, ForeignKey("gg_users.id"), nullable=False)
    user = relationship("User", back_populates="new_tables")
```

#### Step 2: Generate Migration
```bash
alembic revision --autogenerate -m "create new table"
```

#### Step 3: Review Generated Migration
```python
# migrations/versions/xxxx_create_new_table.py
"""create new table

Revision ID: xxxx
Revises: previous_revision
Create Date: 2025-01-27 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.create_table('gg_new_table',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=1000), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['gg_users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_gg_new_table_id'), 'gg_new_table', ['id'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_gg_new_table_id'), table_name='gg_new_table')
    op.drop_table('gg_new_table')
```

### 2. Adding a New Column

#### Step 1: Update the Model
```python
# app/models/existing_table.py
class ExistingTable(Base):
    __tablename__ = "gg_existing_table"
    
    # ... existing columns ...
    
    # Add new column
    new_column = Column(String(100), nullable=True, default="default_value")
```

#### Step 2: Generate Migration
```bash
alembic revision --autogenerate -m "add new column to existing table"
```

#### Step 3: Review Generated Migration
```python
def upgrade() -> None:
    op.add_column('gg_existing_table', sa.Column('new_column', sa.String(length=100), nullable=True))
    op.execute("UPDATE gg_existing_table SET new_column = 'default_value' WHERE new_column IS NULL")

def downgrade() -> None:
    op.drop_column('gg_existing_table', 'new_column')
```

### 3. Updating Column Type

#### Step 1: Update the Model
```python
# app/models/existing_table.py
class ExistingTable(Base):
    __tablename__ = "gg_existing_table"
    
    # ... existing columns ...
    
    # Change column type
    status = Column(Enum('active', 'inactive', 'pending', name='status_enum'), nullable=False, default='pending')
```

#### Step 2: Generate Migration
```bash
alembic revision --autogenerate -m "update column type for status"
```

#### Step 3: Review Generated Migration
```python
def upgrade() -> None:
    # Create new enum type
    op.execute("CREATE TYPE status_enum AS ENUM ('active', 'inactive', 'pending')")
    
    # Update existing data if needed
    op.execute("UPDATE gg_existing_table SET status = 'pending' WHERE status IS NULL OR status NOT IN ('active', 'inactive', 'pending')")
    
    # Alter column type
    op.alter_column('gg_existing_table', 'status',
                    type_=sa.Enum('active', 'inactive', 'pending', name='status_enum'),
                    existing_type=sa.String(),
                    nullable=False,
                    server_default='pending')

def downgrade() -> None:
    op.alter_column('gg_existing_table', 'status',
                    type_=sa.String(),
                    existing_type=sa.Enum('active', 'inactive', 'pending', name='status_enum'),
                    nullable=True)
    op.execute("DROP TYPE status_enum")
```

### 4. Removing a Column

#### Step 1: Update the Model
```python
# app/models/existing_table.py
class ExistingTable(Base):
    __tablename__ = "gg_existing_table"
    
    # ... existing columns ...
    
    # Remove this line:
    # old_column = Column(String(100), nullable=True)
```

#### Step 2: Generate Migration
```bash
alembic revision --autogenerate -m "remove old column from existing table"
```

#### Step 3: Review Generated Migration
```python
def upgrade() -> None:
    op.drop_column('gg_existing_table', 'old_column')

def downgrade() -> None:
    op.add_column('gg_existing_table', sa.Column('old_column', sa.String(length=100), nullable=True))
```

## Automated Deployment Process

### 1. CI/CD Pipeline Integration

#### GitHub Actions Example
```yaml
# .github/workflows/deploy.yml
name: Deploy with Database Migrations

on:
  push:
    branches: [main, develop]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      
      - name: Run database migrations
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
        run: |
          alembic upgrade head
      
      - name: Deploy application
        run: |
          # Your deployment commands here
          echo "Application deployed successfully"
```

#### Docker Compose with Migration Script
```yaml
# docker-compose.yml
version: '3.8'
services:
  app:
    build: .
    depends_on:
      - db
    environment:
      - DATABASE_URL=postgresql://user:password@db:5432/dbname
    command: >
      sh -c "
        echo 'Waiting for database...' &&
        sleep 10 &&
        echo 'Running migrations...' &&
        alembic upgrade head &&
        echo 'Starting application...' &&
        python main.py
      "
  
  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=dbname
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
```

### 2. Pre-deployment Migration Script

```bash
#!/bin/bash
# scripts/run_migrations.sh

set -e

echo "Starting database migration process..."

# Check if database is accessible
echo "Testing database connection..."
python -c "
from app.core.database import engine
from sqlalchemy import text
try:
    with engine.connect() as conn:
        conn.execute(text('SELECT 1'))
    print('Database connection successful')
except Exception as e:
    print(f'Database connection failed: {e}')
    exit(1)
"

# Check current migration status
echo "Current migration status:"
alembic current

# Check if there are pending migrations
echo "Checking for pending migrations:"
alembic check

# Run migrations
echo "Running migrations..."
alembic upgrade head

echo "Migrations completed successfully!"
echo "Current migration status:"
alembic current
```

### 3. Health Check Endpoint

```python
# app/routes/health.py
from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from app.core.database import engine
from app.core.migrations import get_current_revision

router = APIRouter()

@router.get("/health/database")
async def database_health():
    """Check database connectivity and migration status"""
    try:
        # Test database connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        # Get current migration revision
        current_revision = get_current_revision()
        
        return {
            "status": "healthy",
            "database": "connected",
            "current_migration": current_revision,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unhealthy: {str(e)}")

@router.get("/health/migrations")
async def migration_status():
    """Get detailed migration status"""
    try:
        from alembic import command
        from alembic.config import Config
        
        config = Config("alembic.ini")
        
        # Get current revision
        current = command.current(config)
        
        # Get available revisions
        history = command.history(config)
        
        return {
            "current_revision": current,
            "migration_history": history,
            "status": "up_to_date" if not history else "pending"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Migration check failed: {str(e)}")
```

## Best Practices

### 1. Migration Naming Convention
```bash
# Use descriptive names
alembic revision --autogenerate -m "add_user_profile_fields"
alembic revision --autogenerate -m "create_order_items_table"
alembic revision --autogenerate -m "update_product_price_to_decimal"
alembic revision --autogenerate -m "remove_deprecated_api_key_column"
```

### 2. Always Review Generated Migrations
```python
# Before running, always check:
# 1. Generated SQL operations
# 2. Data transformation logic
# 3. Downgrade operations
# 4. Index creation/dropping
# 5. Foreign key constraints
```

### 3. Test Migrations Locally First
```bash
# 1. Create a test database
# 2. Run migrations on test data
# 3. Verify data integrity
# 4. Test rollback scenarios
```

### 4. Handle Data Migration Carefully
```python
def upgrade() -> None:
    # Always handle existing data when changing column types
    op.execute("UPDATE users SET status = 'active' WHERE status IS NULL")
    
    # Use temporary columns for complex changes
    op.add_column('users', sa.Column('new_status', sa.String(50), nullable=True))
    op.execute("UPDATE users SET new_status = status")
    op.drop_column('users', 'status')
    op.alter_column('users', 'new_status', new_column_name='status')
```

### 5. Environment-Specific Configurations
```python
# alembic.ini
[alembic]
# Use environment variables for database URLs
sqlalchemy.url = %(DATABASE_URL)s

# Different configurations for different environments
[dev]
sqlalchemy.url = postgresql://dev_user:dev_pass@localhost:5432/dev_db

[prod]
sqlalchemy.url = postgresql://prod_user:prod_pass@prod_host:5432/prod_db
```

## Troubleshooting

### Common Issues and Solutions

#### 1. Migration Conflicts
```bash
# Check for multiple heads
alembic heads

# Merge conflicting heads
alembic merge -m "merge conflicting migrations" head1 head2
```

#### 2. Failed Migrations
```bash
# Check current status
alembic current

# Check migration history
alembic history

# Downgrade to previous revision
alembic downgrade -1

# Fix the migration file and try again
alembic upgrade +1
```

#### 3. Database Connection Issues
```bash
# Test database connection
python -c "
from app.core.database import engine
from sqlalchemy import text
with engine.connect() as conn:
    conn.execute(text('SELECT 1'))
"
```

#### 4. Migration Lock Issues
```python
# In your migration script, add proper error handling
def upgrade() -> None:
    try:
        # Your migration operations
        op.add_column('table', sa.Column('column', sa.String(50)))
    except Exception as e:
        # Log the error and provide rollback instructions
        print(f"Migration failed: {e}")
        print("Please check the database state and fix manually if needed")
        raise
```

## Summary

To ensure your database changes are automatically reflected across all deployments:

1. **Always use Alembic migrations** for schema changes
2. **Integrate migrations into your CI/CD pipeline**
3. **Test migrations locally** before deploying
4. **Use health check endpoints** to monitor migration status
5. **Follow naming conventions** and best practices
6. **Handle data migration** carefully when changing existing structures
7. **Monitor deployment logs** for migration success/failure

This approach ensures that every time you deploy your application, the database schema is automatically updated to match your current code, maintaining consistency across all environments.
