"""Migration scenario walkthroughs for migration_examples.py.

Split out of scripts/migration_examples.py (2026-09; Raven Style
Compliance Plan Phase 8b line-count reduction).
"""


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
