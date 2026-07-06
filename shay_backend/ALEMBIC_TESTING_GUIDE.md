# Alembic Migration Testing Guide

This guide helps you test Alembic migrations in your dev environment to ensure they work correctly before applying them to production.

## What We're Testing

We've created two test migration files:
1. **`test_add_column_to_users.py`** - Adds a test column to the users table
2. **`test_remove_column_from_users.py`** - Removes the test column after testing

## Testing Steps

### 1. Check Current Migration Status
```bash
# Check which migrations are applied
alembic current

# Check migration history
alembic history

# Check if there are pending migrations
alembic show test_add_column_to_users
```

### 2. Apply the Test Migration
```bash
# Apply the migration to add the test column
alembic upgrade test_add_column_to_users
```

### 3. Verify the Column Was Added
```bash
# Connect to your database and check if the column exists
psql -h localhost -U your_user -d your_database

# In psql, run:
\d gg_users

# You should see the new column: test_column | character varying(50) | nullable
```

### 4. Test the Column in Your Application
- Restart your FastAPI application
- Try to access user data to ensure the new column doesn't break anything
- The column will be `NULL` for existing records, which is fine

### 5. Remove the Test Column
```bash
# Apply the migration to remove the test column
alembic upgrade test_remove_column_from_users
```

### 6. Verify the Column Was Removed
```bash
# Check the table structure again
psql -h localhost -U your_user -d your_database

# In psql, run:
\d gg_users

# The test_column should no longer be visible
```

## Rollback Testing (Optional)

If you want to test rollback functionality:

```bash
# Rollback to before the test column was added
alembic downgrade test_add_column_to_users

# Verify the column is gone
# Then upgrade again
alembic upgrade test_remove_column_from_users
```

## What This Proves

✅ **Migration Creation**: You can create new migration files  
✅ **Migration Application**: Migrations can be applied successfully  
✅ **Column Addition**: New columns can be added to existing tables  
✅ **Column Removal**: Columns can be safely removed  
✅ **Rollback**: Migrations can be rolled back if needed  
✅ **Database Consistency**: Your database schema stays consistent  

## Safety Notes

- These migrations only affect the `gg_users` table
- The test column is nullable, so it won't break existing data
- The column name is clearly marked as a test column
- Both migrations have proper up/down functions

## Cleanup

After testing, you can delete these test migration files:
```bash
rm migrations/versions/test_add_column_to_users.py
rm migrations/versions/test_remove_column_from_users.py
```

## Next Steps

Once you're confident with the migration system:
1. Create real migrations for your actual schema changes
2. Test them in dev first
3. Apply them to staging/production environments
4. Always backup your database before running migrations in production

## Troubleshooting

If you encounter issues:
1. Check the Alembic logs
2. Verify your database connection
3. Ensure you have the correct database permissions
4. Check that the migration dependencies are correct


