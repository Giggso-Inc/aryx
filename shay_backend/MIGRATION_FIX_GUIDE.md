# Migration Fix Guide for Dev Environment

## Problem Summary

Your dev environment is missing critical database migrations, causing these errors:

1. **Messages API Error**: `column "query_id" of relation "gg_messages" does not exist`
2. **Apps API Error**: `column gg_apps.app_key does not exist`

## Root Cause

Your dev environment has a **migration divergence** issue:

- **Local Environment**: At migration `7ed87e41a4d2` (includes both `query_id` and `app_key` columns)
- **Dev Environment**: At migration `ecbda37a5c80` (missing both columns)

## Missing Migrations in Dev

1. `e31613234d66_add_app_key_to_apps_table.py` - Adds `app_key` column to `gg_apps`
2. `7ed87e41a4d2_add_query_id_to_messages_table.py` - Adds `query_id` column to `gg_messages`

## Solution

### Step 1: Deploy the Fix Migration

The migration `86c6d78e1615_add_query_id_column_to_messages.py` has been updated to handle both missing columns. This migration is **idempotent** - it will work whether the columns exist or not.

### Step 2: Apply the Migration

On your dev environment, run:

```bash
alembic upgrade head
```

### Step 3: Verify the Fix

After applying the migration, verify both columns exist:

```sql
-- Check messages table
SELECT column_name FROM information_schema.columns 
WHERE table_name = 'gg_messages' AND column_name = 'query_id';

-- Check apps table  
SELECT column_name FROM information_schema.columns 
WHERE table_name = 'gg_apps' AND column_name = 'app_key';
```

## Prevention Strategy

### 1. Automated Migration Deployment

Add this to your deployment script:

```bash
# Always run migrations before deploying application
alembic upgrade head
```

### 2. Migration Validation

Add these checks to your CI/CD pipeline:

```bash
# Check migration status
alembic current
alembic heads

# Validate schema
alembic check
```

### 3. Environment Synchronization

Before each deployment:

```bash
# Ensure all environments have the same migration state
alembic heads  # Should show only one head
alembic current  # Should be consistent across environments
```

### 4. Deployment Checklist

- [ ] All migration files committed to version control
- [ ] Migration history consistent across environments
- [ ] Database schema validated before deployment
- [ ] Rollback plan tested

## Why This Happened

1. **Multiple developers** created migrations simultaneously
2. **Different branches** deployed to different environments
3. **Migration files not properly synchronized** between environments
4. **Manual database changes** made without proper migration tracking

## Future Prevention

1. **Always use Alembic** for database changes
2. **Never make manual schema changes** in production
3. **Test migrations** in staging before production
4. **Automate migration deployment** in CI/CD pipeline
5. **Regular migration audits** across environments

## Emergency Fix (if migration fails)

If the migration doesn't work, you can manually add the columns:

```sql
-- Add query_id to messages table
ALTER TABLE gg_messages ADD COLUMN query_id UUID;
CREATE INDEX idx_message_query_id ON gg_messages (query_id);

-- Add app_key to apps table
ALTER TABLE gg_apps ADD COLUMN app_key VARCHAR(100);
CREATE UNIQUE INDEX idx_app_key_unique ON gg_apps (app_key);

-- Update existing apps with default app_key
UPDATE gg_apps 
SET app_key = LOWER(REPLACE(app_name, ' ', '_'))
WHERE app_key IS NULL;

-- Make app_key not nullable
ALTER TABLE gg_apps ALTER COLUMN app_key SET NOT NULL;
```

**Note**: This manual approach should only be used as a last resort. Always prefer using Alembic migrations.


