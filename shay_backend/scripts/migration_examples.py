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
"""

import sys
import os
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text, MetaData, Table, Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
import datetime

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

def scenario_create_table():
    """Demonstrate creating a new table"""
    print("=== Scenario 1: Creating a New Table ===")
    
    # Step 1: Define the model (this would be in your models file)
    print("1. Define the model in your models file:")
    print("""
    from sqlalchemy import Column, Integer, String, DateTime, Boolean
    from sqlalchemy.sql import func
    from app.core.database import Base
    
    class ExampleTable(Base):
        __tablename__ = "gg_example_table"
        
        id = Column(Integer, primary_key=True, index=True)
        name = Column(String(255), nullable=False)
        description = Column(String(1000), nullable=True)
        is_active = Column(Boolean, default=True)
        created_at = Column(DateTime(timezone=True), server_default=func.now())
        updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    """)
    
    # Step 2: Generate migration
    print("\n2. Generate migration:")
    print("   alembic revision --autogenerate -m 'create example table'")
    
    # Step 3: Review and run migration
    print("\n3. Review the generated migration file and run:")
    print("   alembic upgrade head")
    
    print("\n✅ Table creation scenario completed!")

def scenario_add_column():
    """Demonstrate adding a new column"""
    print("\n=== Scenario 2: Adding a New Column ===")
    
    # Step 1: Update the model
    print("1. Update your existing model:")
    print("""
    class ExampleTable(Base):
        __tablename__ = "gg_example_table"
        
        # ... existing columns ...
        id = Column(Integer, primary_key=True, index=True)
        name = Column(String(255), nullable=False)
        
        # Add new column
        email = Column(String(255), nullable=True, unique=True)
        phone = Column(String(20), nullable=True)
    """)
    
    # Step 2: Generate migration
    print("\n2. Generate migration:")
    print("   alembic revision --autogenerate -m 'add email and phone to example table'")
    
    # Step 3: Review and run migration
    print("\n3. Review the generated migration file and run:")
    print("   alembic upgrade head")
    
    print("\n✅ Column addition scenario completed!")

def scenario_update_type():
    """Demonstrate updating column type"""
    print("\n=== Scenario 3: Updating Column Type ===")
    
    # Step 1: Update the model
    print("1. Update your existing model:")
    print("""
    from sqlalchemy import Enum
    
    class ExampleTable(Base):
        __tablename__ = "gg_example_table"
        
        # ... existing columns ...
        
        # Change column type from String to Enum
        status = Column(Enum('active', 'inactive', 'pending', name='status_enum'), 
                       nullable=False, default='pending')
    """)
    
    # Step 2: Generate migration
    print("\n2. Generate migration:")
    print("   alembic revision --autogenerate -m 'update status column to enum type'")
    
    # Step 3: Review and run migration
    print("\n3. Review the generated migration file and run:")
    print("   alembic upgrade head")
    
    print("\n✅ Column type update scenario completed!")

def scenario_remove_column():
    """Demonstrate removing a column"""
    print("\n=== Scenario 4: Removing a Column ===")
    
    # Step 1: Update the model
    print("1. Remove the column from your model:")
    print("""
    class ExampleTable(Base):
        __tablename__ = "gg_example_table"
        
        # ... existing columns ...
        id = Column(Integer, primary_key=True, index=True)
        name = Column(String(255), nullable=False)
        email = Column(String(255), nullable=True, unique=True)
        
        # Remove this line:
        # phone = Column(String(20), nullable=True)  # <- Remove this
    """)
    
    # Step 2: Generate migration
    print("\n2. Generate migration:")
    print("   alembic revision --autogenerate -m 'remove phone column from example table'")
    
    # Step 3: Review and run migration
    print("\n3. Review the generated migration file and run:")
    print("   alembic upgrade head")
    
    print("\n✅ Column removal scenario completed!")

def show_migration_commands():
    """Show common migration commands"""
    print("\n=== Common Migration Commands ===")
    print("""
    # Check current migration status
    alembic current
    
    # Check migration history
    alembic history
    
    # Check for pending migrations
    alembic check
    
    # Generate new migration
    alembic revision --autogenerate -m "description of changes"
    
    # Run all pending migrations
    alembic upgrade head
    
    # Run specific number of migrations
    alembic upgrade +1
    
    # Downgrade migrations
    alembic downgrade -1
    
    # Downgrade to specific revision
    alembic downgrade <revision_id>
    
    # Check for multiple heads
    alembic heads
    
    # Merge conflicting heads
    alembic merge -m "merge description" head1 head2
    """)

def show_ci_cd_integration():
    """Show CI/CD integration examples"""
    print("\n=== CI/CD Integration Examples ===")
    print("""
    # GitHub Actions (.github/workflows/deploy.yml)
    - name: Run database migrations
      env:
        DATABASE_URL: ${{ secrets.DATABASE_URL }}
      run: |
        alembic upgrade head
    
    # Docker Compose
    command: >
      sh -c "
        echo 'Running migrations...' &&
        alembic upgrade head &&
        echo 'Starting application...' &&
        python main.py
      "
    
    # Pre-deployment script
    #!/bin/bash
    set -e
    echo "Running migrations..."
    alembic upgrade head
    echo "Migrations completed!"
    """)

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
