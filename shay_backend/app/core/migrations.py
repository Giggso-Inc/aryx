"""
Automatic database migration runner with full automation
"""

import asyncio
import logging
import os
import subprocess
import sys
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)


async def run_migrations() -> bool:
    """
    Run database migrations automatically when the application starts.
    This includes creating migrations if they don't exist.
    
    Returns:
        bool: True if migrations were successful, False otherwise
    """
    try:
        logger.info("🔄 Starting automatic database migrations...")
        
        # Check if we're in a production-like environment
        is_production = os.environ.get("ENVIRONMENT", "").lower() in ["production", "prod", "qa", "staging"]
        
        if is_production:
            logger.info("📦 Production environment detected - running migrations...")
        
        # Initialize migration system if needed
        await initialize_migration_system()
        
        # Run Alembic migrations
        result = await run_alembic_migrations()
        
        if result:
            logger.info("✅ Database migrations completed successfully")
            return True
        else:
            logger.error("❌ Database migrations failed")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error running migrations: {str(e)}")
        return False


async def initialize_migration_system() -> bool:
    """
    Initialize the migration system if it doesn't exist.
    This is fully automated and runs only when needed.
    
    Returns:
        bool: True if initialization was successful, False otherwise
    """
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        # Check if migration system is already initialized
        alembic_ini_path = os.path.join(project_root, "alembic.ini")
        migrations_dir = os.path.join(project_root, "migrations")
        versions_dir = os.path.join(migrations_dir, "versions")
        
        if not os.path.exists(alembic_ini_path):
            logger.info("🔧 Migration system not found. Initializing...")
            
            # Initialize Alembic
            cmd = [sys.executable, "-m", "alembic", "init", "migrations"]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=project_root
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info("✅ Migration system initialized")
                
                # Update env.py with our custom configuration
                await update_env_py(project_root)
                
                # Create initial migration
                await create_initial_migration(project_root)
                
                return True
            else:
                logger.error(f"❌ Failed to initialize migration system: {stderr.decode()}")
                return False
        else:
            logger.info("✅ Migration system already initialized")
            return True
            
    except Exception as e:
        logger.error(f"❌ Error initializing migration system: {str(e)}")
        return False


async def update_env_py(project_root: str) -> bool:
    """Update the env.py file with our custom configuration"""
    try:
        env_py_path = os.path.join(project_root, "migrations", "env.py")
        
        # Our custom env.py content
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
        
        logger.info("✅ Updated migrations/env.py with custom configuration")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error updating env.py: {str(e)}")
        return False


async def create_initial_migration(project_root: str) -> bool:
    """Create initial migration if none exists"""
    try:
        versions_dir = os.path.join(project_root, "migrations", "versions")
        
        # Check if there are any migration files
        if os.path.exists(versions_dir):
            migration_files = [f for f in os.listdir(versions_dir) if f.endswith('.py')]
        else:
            migration_files = []
        
        if not migration_files:
            logger.info("📝 Creating initial migration...")
            
            # Run alembic revision --autogenerate -m "Initial migration"
            cmd = [sys.executable, "-m", "alembic", "revision", "--autogenerate", "-m", "Initial migration"]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=project_root
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info("✅ Initial migration created successfully")
                return True
            else:
                logger.error(f"❌ Failed to create initial migration: {stderr.decode()}")
                return False
        else:
            logger.info(f"📝 Found {len(migration_files)} existing migration files")
            return True
            
    except Exception as e:
        logger.error(f"❌ Error creating initial migration: {str(e)}")
        return False


async def run_alembic_migrations() -> bool:
    """
    Run Alembic migrations using subprocess.
    
    Returns:
        bool: True if migrations were successful, False otherwise
    """
    try:
        # Get the project root directory
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        # Run alembic upgrade head
        cmd = [sys.executable, "-m", "alembic", "upgrade", "head"]
        
        logger.info(f"Running command: {' '.join(cmd)}")
        
        # Run the command
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=project_root
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            logger.info("✅ Alembic migrations completed successfully")
            if stdout:
                logger.info(f"Migration output: {stdout.decode()}")
            return True
        else:
            logger.error(f"❌ Alembic migrations failed with return code {process.returncode}")
            if stderr:
                logger.error(f"Migration error: {stderr.decode()}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error running Alembic migrations: {str(e)}")
        return False


# For manual execution (development only)
if __name__ == "__main__":
    import asyncio
    
    async def main():
        # Run migrations
        success = await run_migrations()
        if not success:
            sys.exit(1)
    
    asyncio.run(main()) 