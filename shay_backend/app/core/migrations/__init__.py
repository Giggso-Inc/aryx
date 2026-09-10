"""
Automatic database migration runner with full automation.

Package split from the former single-file app/core/migrations.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md:
- runner.py  — run_migrations() / run_alembic_migrations() (the top-level
  orchestration + the `alembic upgrade head` subprocess call)
- setup.py   — initialize_migration_system() / update_env_py() /
  create_initial_migration() (one-time Alembic scaffolding)

Re-exports every name external code imported from `app.core.migrations`
before the split (grepped: main.py imports run_migrations;
tests/conftest.py patches "app.core.migrations.run_migrations" directly).
"""

from app.core.migrations.runner import run_alembic_migrations, run_migrations
from app.core.migrations.setup import create_initial_migration, initialize_migration_system, update_env_py

__all__ = [
    "run_migrations",
    "run_alembic_migrations",
    "initialize_migration_system",
    "update_env_py",
    "create_initial_migration",
]


# For manual execution (development only)
if __name__ == "__main__":
    import asyncio
    import sys

    async def main() -> None:
        # Run migrations
        success = await run_migrations()
        if not success:
            sys.exit(1)

    asyncio.run(main())
