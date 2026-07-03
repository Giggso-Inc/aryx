# Database Migration Guide

## Overview

This project uses **Alembic** for database migrations with automatic execution on application startup. This ensures that database schema changes are automatically applied when you deploy your code to QA and production environments.

## How It Works

### 1. **Automatic Migration Execution**
- Migrations run automatically when the application starts
- No manual intervention required in QA/Prod environments
- Graceful handling of migration failures

### 2. **Migration Files**
- All migrations are stored in `migrations/versions/`
- Each migration file contains upgrade and downgrade logic
- Migrations are versioned and tracked in the database

### 3. **Environment Detection**
- The system detects production-like environments automatically
- Migrations run in QA, staging, and production environments
- Development environment can skip migrations if needed

## Setup Instructions

### Step 1: Initialize Migration System (Development Only)

```bash
# Run this once in development to set up the migration system
python init_migrations.py
```

This will:
- Create `alembic.ini` configuration file
- Set up `migrations/` directory structure
- Create initial migration with all current models
- Configure the migration environment

### Step 2: Install Dependencies

```bash
# Install Alembic
pip install alembic==1.12.1
```

### Step 3: Create New Migrations (Development)

When you make schema changes:

```bash
# Generate a new migration
python -m alembic revision --autogenerate -m "Description of changes"

# Apply migrations locally (optional)
python -m alembic upgrade head
```

### Step 4: Deploy to QA/Production

The migrations will run automatically when the application starts:

```bash
# Your normal deployment process
# Migrations run automatically on startup
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Migration Commands

### Development Commands

```bash
# Initialize migration system (first time only)
python init_migrations.py

# Create new migration
python -m alembic revision --autogenerate -m "Add new table"

# Apply all pending migrations
python -m alembic upgrade head

# Apply specific migration
python -m alembic upgrade <revision_id>

# Rollback one migration
python -m alembic downgrade -1

# Check current migration status
python -m alembic current

# View migration history
python -m alembic history
```

### Production Commands

```bash
# Check migration status (safe to run)
python -m alembic current

# View migration history (safe to run)
python -m alembic history
```

## File Structure

```
project/
├── alembic.ini                 # Alembic configuration
├── migrations/
│   ├── env.py                  # Migration environment
│   ├── script.py.mako          # Migration template
│   └── versions/               # Migration files
│       ├── 001_initial.py
│       ├── 002_add_vault.py
│       └── ...
├── app/
│   └── core/
│       └── migrations.py       # Automatic migration runner
└── main.py                     # Application startup
```

## Environment Variables

The migration system uses these environment variables:

```bash
# Database connection
DATABASE_URL="postgresql+asyncpg://user:password@host:port/dbname"

# Environment detection (optional)
ENVIRONMENT="production"  # or "qa", "staging", "development"
```

## Automatic Migration Process

### 1. Application Startup
```python
# In main.py - lifespan event
async def lifespan(app: FastAPI):
    # Startup
    migration_success = await run_migrations()
    if not migration_success:
        logger.warning("Migrations failed, but continuing startup")
    
    yield
    
    # Shutdown
```

### 2. Migration Execution
```python
# In app/core/migrations.py
async def run_migrations() -> bool:
    # Detect environment
    is_production = os.environ.get("ENVIRONMENT", "").lower() in ["production", "prod", "qa", "staging"]
    
    # Run Alembic migrations
    result = await run_alembic_migrations()
    
    return result
```

### 3. Error Handling
- Migration failures don't stop application startup
- Errors are logged for debugging
- Application continues with existing schema

## Best Practices

### 1. **Migration Naming**
```bash
# Good migration names
python -m alembic revision --autogenerate -m "Add user table"
python -m alembic revision --autogenerate -m "Add email column to users"
python -m alembic revision --autogenerate -m "Create vault table"

# Avoid generic names
python -m alembic revision --autogenerate -m "Update"
python -m alembic revision --autogenerate -m "Fix"
```

### 2. **Testing Migrations**
```bash
# Test migrations locally before deploying
python -m alembic upgrade head

# Test rollback if needed
python -m alembic downgrade -1
```

### 3. **Review Migration Files**
Always review generated migration files before committing:

```python
# Example migration file
def upgrade() -> None:
    # Review these changes
    op.create_table('gg_vault',
        sa.Column('giggso_vault_id', sa.UUID(), nullable=False),
        sa.Column('resource_id', sa.UUID(), nullable=True),
        # ... more columns
    )

def downgrade() -> None:
    # Review rollback logic
    op.drop_table('gg_vault')
```

## Troubleshooting

### Common Issues

#### 1. **Migration Conflicts**
```bash
# If migrations are out of sync
python -m alembic stamp head  # Mark as up-to-date
python -m alembic upgrade head  # Apply pending migrations
```

#### 2. **Database Connection Issues**
```bash
# Check database connection
python -c "from app.core.config import settings; print(settings.DATABASE_URL)"
```

#### 3. **Model Import Issues**
```bash
# Ensure all models are imported in migrations/env.py
from app.models import *  # This should import all models
```

#### 4. **Migration Not Running**
```bash
# Check if migrations are enabled
echo $ENVIRONMENT  # Should be "production", "qa", etc.

# Check migration status
python -m alembic current
```

### Debug Commands

```bash
# Check migration status
python -m alembic current

# View migration history
python -m alembic history

# Check database schema
python -c "from app.core.database import engine; print(engine.url)"

# Test migration generation
python -m alembic revision --autogenerate -m "Test migration"
```

## Deployment Checklist

### Before Deployment
- [ ] All migrations are committed to version control
- [ ] Migrations have been tested locally
- [ ] Database connection is configured correctly
- [ ] Environment variables are set

### After Deployment
- [ ] Check application logs for migration success/failure
- [ ] Verify database schema matches expectations
- [ ] Test application functionality

## Security Considerations

### 1. **Database Permissions**
Ensure your database user has:
- `CREATE TABLE` permissions
- `ALTER TABLE` permissions
- `DROP TABLE` permissions (for rollbacks)

### 2. **Backup Strategy**
```bash
# Always backup before major migrations
pg_dump your_database > backup_before_migration.sql
```

### 3. **Rollback Plan**
```bash
# Keep rollback commands ready
python -m alembic downgrade -1  # Rollback one migration
python -m alembic downgrade <revision_id>  # Rollback to specific version
```

## Monitoring

### Log Messages to Watch For
```
✅ Database migrations completed successfully
⚠️ Database migrations failed, but continuing with application startup
❌ Error running migrations: <error details>
```

### Health Check Endpoint
```bash
# Check if migrations are working
curl http://your-app/health
```

## Migration Examples

### Adding a New Table
```bash
# 1. Add model to app/models/
# 2. Generate migration
python -m alembic revision --autogenerate -m "Add new table"
# 3. Review migration file
# 4. Commit and deploy
```

### Adding a Column
```bash
# 1. Add column to model
# 2. Generate migration
python -m alembic revision --autogenerate -m "Add column to table"
# 3. Review migration file
# 4. Commit and deploy
```

### Renaming a Column
```bash
# 1. Update model with new column name
# 2. Generate migration
python -m alembic revision --autogenerate -m "Rename column"
# 3. Review migration file (may need manual editing)
# 4. Commit and deploy
```

This migration system ensures that your database schema stays in sync with your code across all environments without manual intervention! 