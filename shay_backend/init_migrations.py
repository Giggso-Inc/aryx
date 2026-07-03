#!/usr/bin/env python3
"""
Initialize Alembic migrations for the project
"""

import os
import sys
import subprocess
from pathlib import Path

def init_alembic():
    """Initialize Alembic migration system"""
    try:
        print("🔧 Initializing Alembic migrations...")
        
        # Check if alembic.ini already exists
        if os.path.exists("alembic.ini"):
            print("⚠️ alembic.ini already exists. Skipping initialization.")
            return True
        
        # Run alembic init migrations
        cmd = [sys.executable, "-m", "alembic", "init", "migrations"]
        print(f"Running: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ Alembic initialized successfully")
            
            # Update the env.py file with our custom configuration
            update_env_py()
            
            # Create initial migration
            create_initial_migration()
            
            return True
        else:
            print(f"❌ Failed to initialize Alembic: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Error initializing Alembic: {str(e)}")
        return False


def update_env_py():
    """Update the env.py file with our custom configuration"""
    try:
        env_py_path = "migrations/env.py"
        
        # Read the current env.py
        with open(env_py_path, 'r') as f:
            content = f.read()
        
        # Replace the content with our custom env.py
        custom_env_py = '''from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import os
import sys

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.database import Base
from app.models import *  # Import all models

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_url():
    """Get database URL from environment or settings"""
    return settings.DATABASE_URL


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # Override the URL from config with our settings
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
'''
        
        # Write the custom env.py
        with open(env_py_path, 'w') as f:
            f.write(custom_env_py)
        
        print("✅ Updated migrations/env.py with custom configuration")
        
    except Exception as e:
        print(f"❌ Error updating env.py: {str(e)}")


def create_initial_migration():
    """Create initial migration"""
    try:
        print("📝 Creating initial migration...")
        
        # Run alembic revision --autogenerate -m "Initial migration"
        cmd = [sys.executable, "-m", "alembic", "revision", "--autogenerate", "-m", "Initial migration"]
        print(f"Running: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ Initial migration created successfully")
            return True
        else:
            print(f"❌ Failed to create initial migration: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Error creating initial migration: {str(e)}")
        return False


def main():
    """Main function"""
    print("🚀 Starting migration system initialization...")
    
    success = init_alembic()
    
    if success:
        print("\n✅ Migration system initialized successfully!")
        print("\n📋 Next steps:")
        print("1. Review the generated migration files in migrations/versions/")
        print("2. Test migrations locally: python -m alembic upgrade head")
        print("3. Deploy to QA/Prod - migrations will run automatically on startup")
    else:
        print("\n❌ Failed to initialize migration system")
        sys.exit(1)


if __name__ == "__main__":
    main() 