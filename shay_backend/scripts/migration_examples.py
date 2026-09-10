#!/usr/bin/env python3
"""
Migration Examples Script

This script demonstrates practical examples of how to implement
the migration scenarios described in the MIGRATION_BEST_PRACTICES_GUIDE.md

Usage:
    python scripts/migration_examples.py [scenario]

Scenarios:
    - create_table: Create a new table
    - add_column: Add a new column to existing table
    - update_type: Update column type
    - remove_column: Remove a column
    - all: Run all scenarios

As of the Raven Style Compliance Plan's Phase 8b (2026-09), split into
`migration_examples_scenarios.py` (the four scenario walkthroughs) and
`migration_examples_docs.py` (reference command/CI-CD printouts) — both
imported here so the `python scripts/migration_examples.py` invocation
is unchanged.
"""

import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import os

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text, MetaData, Table, Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
import datetime

from scripts.migration_examples_scenarios import (
    scenario_add_column,
    scenario_create_table,
    scenario_remove_column,
    scenario_update_type,
)
from scripts.migration_examples_docs import show_ci_cd_integration, show_migration_commands


def setup_alembic_config():
    """Setup Alembic configuration"""
    config = Config("alembic.ini")
    return config


def create_example_model():
    """Create an example model for demonstration"""
    class ExampleTable:
        __tablename__ = "gg_example_table"

        id = Column(Integer, primary_key=True, index=True)
        name = Column(String(255), nullable=False)
        description = Column(String(1000), nullable=True)
        is_active = Column(Boolean, default=True)
        created_at = Column(DateTime(timezone=True), server_default=func.now())
        updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    return ExampleTable


def main():
    """Main function to run migration scenarios"""
    if len(sys.argv) < 2:
        print("Usage: python scripts/migration_examples.py [scenario]")
        print("Scenarios: create_table, add_column, update_type, remove_column, all")
        print("\nRunning all scenarios...\n")
        scenario = "all"
    elif sys.argv[1] in ["-h", "--help", "help"]:
        print("Usage: python scripts/migration_examples.py [scenario]")
        print("Scenarios: create_table, add_column, update_type, remove_column, all")
        print("\nExamples:")
        print("  python scripts/migration_examples.py create_table")
        print("  python scripts/migration_examples.py add_column")
        print("  python scripts/migration_examples.py all")
        return
    else:
        scenario = sys.argv[1]

    if scenario == "create_table":
        scenario_create_table()
    elif scenario == "add_column":
        scenario_add_column()
    elif scenario == "update_type":
        scenario_update_type()
    elif scenario == "remove_column":
        scenario_remove_column()
    elif scenario == "all":
        scenario_create_table()
        scenario_add_column()
        scenario_update_type()
        scenario_remove_column()
    else:
        print(f"Unknown scenario: {scenario}")
        print("Available scenarios: create_table, add_column, update_type, remove_column, all")
        return

    show_migration_commands()
    show_ci_cd_integration()

    print("\n" + "="*60)
    print("🎉 Migration examples completed!")
    print("📚 Check MIGRATION_BEST_PRACTICES_GUIDE.md for detailed information")
    print("🔧 Remember to always test migrations locally before deploying")
    print("="*60)


if __name__ == "__main__":
    main()
