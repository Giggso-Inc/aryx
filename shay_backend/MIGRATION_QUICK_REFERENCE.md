# Migration Quick Reference Card

## 🚀 Quick Start Commands

```bash
# Check current status
alembic current

# Check for pending migrations
alembic check

# View migration history
alembic history

# View detailed history
alembic history --verbose
```

## 📝 Creating Migrations

```bash
# Auto-generate migration from model changes
alembic revision --autogenerate -m "description of changes"

# Create empty migration (manual)
alembic revision -m "description of changes"
```

## 🔄 Running Migrations

```bash
# Run all pending migrations
alembic upgrade head

# Run specific number of migrations
alembic upgrade +1

# Run to specific revision
alembic upgrade <revision_id>

# Run to specific revision (relative)
alembic upgrade +2
```

## ⬇️ Rolling Back Migrations

```bash
# Rollback one migration
alembic downgrade -1

# Rollback to specific revision
alembic downgrade <revision_id>

# Rollback to base (remove all tables)
alembic downgrade base
```

## 🔍 Troubleshooting

```bash
# Check for multiple heads
alembic heads

# Merge conflicting heads
alembic merge -m "merge description" head1 head2

# Show current heads
alembic show <revision_id>
```

## 📊 Common Scenarios

### 1. Create New Table
```python
# 1. Add model to models/
# 2. Generate migration
alembic revision --autogenerate -m "create new table"

# 3. Review and run
alembic upgrade head
```

### 2. Add New Column
```python
# 1. Update existing model
# 2. Generate migration
alembic revision --autogenerate -m "add new column"

# 3. Review and run
alembic upgrade head
```

### 3. Change Column Type
```python
# 1. Update model with new type
# 2. Generate migration
alembic revision --autogenerate -m "change column type"

# 3. Review and run
alembic upgrade head
```

### 4. Remove Column
```python
# 1. Remove column from model
# 2. Generate migration
alembic revision --autogenerate -m "remove column"

# 3. Review and run
alembic upgrade head
```

## 🚨 Important Notes

- **Always review** generated migrations before running
- **Test locally** before deploying to production
- **Backup database** before major schema changes
- **Use descriptive** migration names
- **Handle data** carefully when changing existing structures

## 🔧 CI/CD Integration

### GitHub Actions
```yaml
- name: Run migrations
  run: alembic upgrade head
```

### Docker Compose
```yaml
command: >
  sh -c "
    alembic upgrade head &&
    python main.py
  "
```

### Pre-deployment Script
```bash
#!/bin/bash
set -e
alembic upgrade head
echo "Migrations completed!"
```

## 📚 Full Documentation

For complete details, see: [MIGRATION_BEST_PRACTICES_GUIDE.md](./MIGRATION_BEST_PRACTICES_GUIDE.md)

## 🆘 Need Help?

```bash
# Show help for any command
alembic --help
alembic upgrade --help
alembic revision --help

# Check Alembic version
alembic --version
```
