# Database Migration Tools & Guides

This directory contains comprehensive tools and guides for managing database migrations using Alembic in your FastAPI backend project.

## 📚 What's Included

### 1. **MIGRATION_BEST_PRACTICES_GUIDE.md** - Complete Migration Guide
- **4 Main Scenarios**: Create table, Add column, Update column type, Remove column
- **Step-by-step instructions** for each scenario
- **CI/CD integration** examples (GitHub Actions, Docker Compose)
- **Best practices** and troubleshooting tips
- **Health check endpoints** for monitoring migration status

### 2. **MIGRATION_QUICK_REFERENCE.md** - Quick Reference Card
- **Common commands** at your fingertips
- **Quick scenarios** for everyday use
- **Troubleshooting** commands
- **CI/CD snippets** for immediate use

### 3. **scripts/migration_examples.py** - Interactive Examples
- **Run scenarios**: `python scripts/migration_examples.py [scenario]`
- **Available scenarios**: `create_table`, `add_column`, `update_type`, `remove_column`, `all`
- **Interactive demonstrations** of each migration type
- **Command examples** and CI/CD integration snippets

### 4. **scripts/deploy_with_migrations.sh** - Automated Deployment Script
- **Automatic migration execution** before app startup
- **Database health checks** and connection validation
- **Multiple modes**: full deployment, migration-only, check-only
- **Error handling** and logging
- **Cross-platform** deployment automation

## 🚀 Quick Start

### 1. Check Current Status
```bash
alembic current
alembic history
```

### 2. Create a New Migration
```bash
# After updating your models
alembic revision --autogenerate -m "description of changes"
```

### 3. Apply Migrations
```bash
alembic upgrade head
```

### 4. Run Examples
```bash
# See all scenarios
python scripts/migration_examples.py all

# See specific scenario
python scripts/migration_examples.py create_table
```

## 🔄 Migration Workflow

### For Developers
1. **Update your SQLAlchemy models** in `app/models/`
2. **Generate migration**: `alembic revision --autogenerate -m "description"`
3. **Review the generated migration** file
4. **Test locally**: `alembic upgrade head`
5. **Commit both model changes and migration files**

### For Deployment
1. **Code is deployed** to your environment
2. **Deployment script runs** automatically
3. **Database connection is verified**
4. **Migrations are executed** automatically
5. **Application starts** with updated schema

## 🌍 Multi-Environment Support

### Development
- Local database with test data
- Manual migration testing
- Safe rollback capabilities

### Staging/Production
- Automated migration execution
- Health checks and validation
- Error handling and logging
- Zero-downtime deployments

## 🛠️ Integration Examples

### GitHub Actions
```yaml
- name: Run Database Migrations
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

### Kubernetes
```yaml
command: ["/bin/bash", "-c"]
args: ["alembic upgrade head && python main.py"]
```

## 🔍 Monitoring & Health Checks

### Built-in Endpoints
- `/health/database` - Database connectivity and migration status
- `/health/migrations` - Detailed migration information

### Deployment Script Features
- Database connection validation
- Migration status checking
- Application startup validation
- Comprehensive logging

## 🚨 Important Notes

1. **Always test migrations locally** before deploying
2. **Review generated migrations** for accuracy
3. **Backup production databases** before major changes
4. **Use descriptive migration names** for clarity
5. **Handle data migration** carefully when changing existing structures

## 📖 Documentation Structure

```
├── MIGRATION_BEST_PRACTICES_GUIDE.md    # Complete guide
├── MIGRATION_QUICK_REFERENCE.md         # Quick reference
├── scripts/
│   ├── migration_examples.py            # Interactive examples
│   └── deploy_with_migrations.sh        # Deployment automation
└── README_MIGRATIONS.md                 # This file
```

## 🆘 Need Help?

### Common Issues
- **Migration conflicts**: Use `alembic heads` and `alembic merge`
- **Failed migrations**: Check logs and use `alembic downgrade`
- **Connection issues**: Verify database configuration

### Resources
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [FastAPI Database Documentation](https://fastapi.tiangolo.com/tutorial/sql-databases/)

## 🎯 Next Steps

1. **Read the complete guide**: `MIGRATION_BEST_PRACTICES_GUIDE.md`
2. **Try the examples**: `python scripts/migration_examples.py all`
3. **Integrate with your CI/CD**: Use the provided examples
4. **Set up health checks**: Implement the monitoring endpoints
5. **Test the deployment script**: `./scripts/deploy_with_migrations.sh --help`

---

**Remember**: These tools ensure that every deployment automatically updates your database schema to match your current code, maintaining consistency across all environments! 🚀
