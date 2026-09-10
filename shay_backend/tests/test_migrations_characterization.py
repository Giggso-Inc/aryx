"""
Golden-master / characterization tests for app/core/migrations.py.

Purpose: migrations.py is 308 lines with zero dedicated test coverage before
this file (tests/conftest.py only patches run_migrations wholesale as an
AsyncMock so main.py's app fixture doesn't try to run real migrations — it
never exercises the function bodies). It was split per
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md into a package:
- app/core/migrations/runner.py — run_migrations(), run_alembic_migrations()
- app/core/migrations/setup.py  — initialize_migration_system(),
  update_env_py(), create_initial_migration()
- app/core/migrations/env_template.py — the CUSTOM_ENV_PY string constant

CRITICAL GOTCHA: patch() targets below point at the submodule that actually
owns each name (runner.py or setup.py), NOT app.core.migrations (the
re-exporting package __init__), because unittest.mock.patch only rewrites
the attribute at the exact module path where it's looked up at call time.

Every function here shells out via asyncio.create_subprocess_exec or touches
the filesystem (alembic.ini / migrations/ / migrations/versions/), so every
test mocks at that boundary. No real subprocess is ever spawned and no real
file is ever written.

asyncio.run() is used instead of pytest-asyncio (not installed), matching
tests/test_channels_characterization.py's pattern.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from app.core.migrations import (
    create_initial_migration,
    initialize_migration_system,
    run_alembic_migrations,
    run_migrations,
    update_env_py,
)


def _mock_process(returncode: int, stdout: bytes = b"", stderr: bytes = b""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


# ---------------------------------------------------------------------------
# run_migrations (defined in app.core.migrations.runner)
# ---------------------------------------------------------------------------
class TestRunMigrations:
    def test_returns_true_when_alembic_succeeds(self):
        with patch("app.core.migrations.runner.initialize_migration_system", new_callable=AsyncMock, return_value=True), \
             patch("app.core.migrations.runner.run_alembic_migrations", new_callable=AsyncMock, return_value=True):
            assert asyncio.run(run_migrations()) is True

    def test_returns_false_when_alembic_fails(self):
        with patch("app.core.migrations.runner.initialize_migration_system", new_callable=AsyncMock, return_value=True), \
             patch("app.core.migrations.runner.run_alembic_migrations", new_callable=AsyncMock, return_value=False):
            assert asyncio.run(run_migrations()) is False

    def test_returns_false_and_swallows_exception(self):
        with patch("app.core.migrations.runner.initialize_migration_system", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            # Documents current behavior: any exception anywhere in the flow
            # is caught and converted to a plain `False`, never re-raised.
            assert asyncio.run(run_migrations()) is False

    def test_runs_even_when_initialize_migration_system_returns_false(self):
        """Pre-existing quirk: the return value of initialize_migration_system
        is never checked — run_alembic_migrations always runs regardless."""
        with patch("app.core.migrations.runner.initialize_migration_system", new_callable=AsyncMock, return_value=False), \
             patch("app.core.migrations.runner.run_alembic_migrations", new_callable=AsyncMock, return_value=True) as mock_run:
            assert asyncio.run(run_migrations()) is True
            mock_run.assert_awaited_once()


# ---------------------------------------------------------------------------
# initialize_migration_system (defined in app.core.migrations.setup)
# ---------------------------------------------------------------------------
class TestInitializeMigrationSystem:
    def test_already_initialized_short_circuits(self):
        with patch("app.core.migrations.setup.os.path.exists", return_value=True):
            assert asyncio.run(initialize_migration_system()) is True

    def test_initializes_when_alembic_ini_missing_and_alembic_succeeds(self):
        with patch("app.core.migrations.setup.os.path.exists", return_value=False), \
             patch("app.core.migrations.setup.asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=_mock_process(0)), \
             patch("app.core.migrations.setup.update_env_py", new_callable=AsyncMock, return_value=True) as mock_env, \
             patch("app.core.migrations.setup.create_initial_migration", new_callable=AsyncMock, return_value=True) as mock_init:
            assert asyncio.run(initialize_migration_system()) is True
            mock_env.assert_awaited_once()
            mock_init.assert_awaited_once()

    def test_returns_false_when_alembic_init_fails(self):
        with patch("app.core.migrations.setup.os.path.exists", return_value=False), \
             patch("app.core.migrations.setup.asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=_mock_process(1, stderr=b"init failed")):
            assert asyncio.run(initialize_migration_system()) is False

    def test_returns_false_and_swallows_exception(self):
        with patch("app.core.migrations.setup.os.path.exists", side_effect=OSError("fs error")):
            assert asyncio.run(initialize_migration_system()) is False


# ---------------------------------------------------------------------------
# update_env_py (defined in app.core.migrations.setup)
# ---------------------------------------------------------------------------
class TestUpdateEnvPy:
    def test_writes_custom_env_py_and_returns_true(self):
        m = mock_open()
        with patch("app.core.migrations.setup.open", m, create=True):
            assert asyncio.run(update_env_py("/fake/root")) is True
        m.assert_called_once_with("/fake/root/migrations/env.py", "w")
        written = "".join(c.args[0] for c in m().write.call_args_list)
        assert "from app.core.database import Base" in written
        assert "run_migrations_online" in written

    def test_returns_false_and_swallows_exception_on_write_failure(self):
        with patch("app.core.migrations.setup.open", side_effect=OSError("disk full"), create=True):
            assert asyncio.run(update_env_py("/fake/root")) is False


# ---------------------------------------------------------------------------
# create_initial_migration (defined in app.core.migrations.setup)
# ---------------------------------------------------------------------------
class TestCreateInitialMigration:
    def test_creates_migration_when_versions_dir_empty(self):
        with patch("app.core.migrations.setup.os.path.exists", return_value=False), \
             patch("app.core.migrations.setup.asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=_mock_process(0)):
            assert asyncio.run(create_initial_migration("/fake/root")) is True

    def test_skips_when_migration_files_already_exist(self):
        with patch("app.core.migrations.setup.os.path.exists", return_value=True), \
             patch("app.core.migrations.setup.os.listdir", return_value=["0001_initial.py"]), \
             patch("app.core.migrations.setup.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            assert asyncio.run(create_initial_migration("/fake/root")) is True
            mock_exec.assert_not_awaited()

    def test_returns_false_when_alembic_revision_fails(self):
        with patch("app.core.migrations.setup.os.path.exists", return_value=False), \
             patch("app.core.migrations.setup.asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=_mock_process(1, stderr=b"revision failed")):
            assert asyncio.run(create_initial_migration("/fake/root")) is False

    def test_returns_false_and_swallows_exception(self):
        with patch("app.core.migrations.setup.os.path.exists", side_effect=OSError("fs error")):
            assert asyncio.run(create_initial_migration("/fake/root")) is False


# ---------------------------------------------------------------------------
# run_alembic_migrations (defined in app.core.migrations.runner)
# ---------------------------------------------------------------------------
class TestRunAlembicMigrations:
    def test_returns_true_on_success(self):
        with patch("app.core.migrations.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=_mock_process(0, stdout=b"upgraded")):
            assert asyncio.run(run_alembic_migrations()) is True

    def test_returns_false_on_nonzero_returncode(self):
        with patch("app.core.migrations.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=_mock_process(1, stderr=b"upgrade failed")):
            assert asyncio.run(run_alembic_migrations()) is False

    def test_returns_false_and_swallows_exception(self):
        with patch("app.core.migrations.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock, side_effect=OSError("no alembic")):
            assert asyncio.run(run_alembic_migrations()) is False
