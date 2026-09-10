#!/usr/bin/env python3
"""
Template Setup Script

This script sets up the template functionality by:
1. Creating the gg_templates table with current schema
2. Setting up the template directory
3. Creating sample template files
4. Running tests to verify everything works

Current Schema Fields:
- id (UUID, PRIMARY KEY)
- template_id (VARCHAR, UNIQUE, auto-generated format: TMPLT_INVITE_XXX)
- template_name (VARCHAR, NOT NULL)
- file_path (VARCHAR, nullable)
- file_size (VARCHAR, nullable)
- additional_config (JSONB, default {})
- created_datetime (TIMESTAMP)
- updated_datetime (TIMESTAMP)

Usage:
    python scripts/setup_templates.py

The script will:
1. Check prerequisites
2. Create template directory
3. Create sample template files
4. Create database table
5. Run tests
6. Show usage examples

Author: AI Assistant
Date: 2025-01-27
Version: 2.0.0

As of the Raven Style Compliance Plan's Phase 8b (2026-09), split into
`setup_templates_content.py` (template directory + sample-file content),
`setup_templates_db.py` (engine/table/record helpers), and
`setup_templates_docs.py` (usage printout) — all imported here so the
`python scripts/setup_templates.py` invocation is unchanged.
"""

import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.setup_templates_content import setup_template_directory, test_template_files
from scripts.setup_templates_db import (
    create_database_table,
    create_sample_template_record,
    get_database_engine,
    test_database_connection,
)
from scripts.setup_templates_docs import show_usage_examples


def check_prerequisites():
    """Check if all prerequisites are met"""
    print("🔍 Checking prerequisites...")

    # Check if we're in the right directory
    if not (project_root / "main.py").exists():
        print("❌ Please run this script from the project root directory")
        return False

    # Check if Python version is adequate
    if sys.version_info < (3, 8):
        print("❌ Python 3.8 or higher is required")
        return False

    print("✅ Prerequisites check passed")
    return True


def main():
    """Main setup function"""
    print("🚀 Template Setup Script")
    print("=" * 50)

    try:
        # Check prerequisites
        if not check_prerequisites():
            sys.exit(1)

        # Setup template directory
        if not setup_template_directory():
            print("❌ Failed to setup template directory")
            sys.exit(1)

        # Get database engine
        print("\n🔌 Connecting to database...")
        engine = get_database_engine()

        # Create database table
        if not create_database_table(engine):
            print("❌ Failed to create database table")
            sys.exit(1)

        # Create sample template record
        create_sample_template_record(engine)

        # Test everything
        db_test = test_database_connection(engine)
        file_test = test_template_files()

        # Show results
        print("\n" + "=" * 50)
        print("🎉 Template setup completed!")
        print(f"📊 Results:")
        print(f"   - Template directory: {'✅ Success' if file_test else '❌ Failed'}")
        print(f"   - Database table: {'✅ Success' if db_test else '❌ Failed'}")
        print(f"   - Sample files: Created")
        print(f"   - Sample record: Created")
        print(f"   - API endpoints: Ready")

        if db_test and file_test:
            print("\n✅ All components are working correctly!")
            show_usage_examples()
        else:
            print("\n⚠️ Some components failed. Please check the errors above.")
            sys.exit(1)

    except Exception as e:
        print(f"❌ Setup failed: {str(e)}")
        print("\nTroubleshooting:")
        print("1. Check your DATABASE_URL environment variable")
        print("2. Ensure database is running and accessible")
        print("3. Verify file system permissions")
        print("4. Check Python dependencies are installed")
        sys.exit(1)


if __name__ == "__main__":
    main()
