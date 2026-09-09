"""Reference command/CI-CD printouts for migration_examples.py.

Split out of scripts/migration_examples.py (2026-09; Raven Style
Compliance Plan Phase 8b line-count reduction).
"""


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
