"""
Top-level automatic migration runner: orchestrates one-time setup
(app.core.migrations.setup) and the actual `alembic upgrade head` subprocess.

Split out of app/core/migrations.py — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.
"""

import asyncio
import logging
import os
import sys

from app.core.migrations.setup import initialize_migration_system

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


async def run_alembic_migrations() -> bool:
    """
    Run Alembic migrations using subprocess.

    Returns:
        bool: True if migrations were successful, False otherwise
    """
    try:
        # Get the project root directory
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

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
